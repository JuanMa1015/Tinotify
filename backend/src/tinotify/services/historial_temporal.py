"""Historial real de actuaciones SOLO en memoria, con expiración e invalidación.

Una lectura SIGAC manual y validada (`leer_historial_validado`) se verifica contra las huellas de la línea base
v2 y se conserva aquí unos minutos para que la app Android la consulte por el enlace local. Nunca se escribe en
SQLite, Supabase ni Render, nunca se registra en logs y no modifica la línea base. Las credenciales SIGAC jamás
llegan a este módulo: la autenticación ocurre en la terminal que inicia el proceso.

Limitación honesta: Python no garantiza borrar la memoria física; «invalidar» elimina todas las referencias
conservadas y el recolector las libera, pero no es un borrado criptográfico.
"""

from collections import Counter, deque
from dataclasses import dataclass
import threading
import time
from uuid import uuid4

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.parsers.presentacion import presentar, vista_previa
from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, leer_historial_validado
from tinotify.persistence.sqlite_local import BINDING_LOCAL, CREDENCIAL_LOCAL
from tinotify.services.consulta_real_local import (
    IdentidadExpedienteNoVerificada, caso_local, exigir_identidad_expediente,
)

TTL_PREDETERMINADO_S = 1200
TTL_MAXIMO_S = 3600
VISTA_PREVIA = 160


class HistorialNoCorresponde(ValueError):
    """La lectura no contiene la línea base v2 o no pertenece al expediente: no se conserva nada."""


@dataclass(frozen=True)
class _Sesion:
    sesion: str
    caso: str
    vence: float
    items: tuple


def referencia_v2(servicio, caso):
    """[(local_id, version_hash)] de la línea base autoritativa (tabla actuaciones), en orden. Solo lectura."""
    with servicio.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
        seguimiento = unidad.buscar_seguimiento(INSTANCIA_REAL, caso)
        registros = unidad.leer_caso(seguimiento, BINDING_LOCAL) if seguimiento else None
    if not registros or not registros["records"]:
        raise HistorialNoCorresponde("No existe una línea base v2 para este expediente")
    return [(r["local_id"], r["version_hash"]) for r in registros["records"]]


def construir_items(actuaciones, referencia, huella=None):
    """Asocia cada actuación leída a la línea base respetando multiplicidades.

    Exige que TODAS las huellas de v2 estén en la lectura (con su multiplicidad). Las huellas iguales son contenido
    idéntico, de modo que cualquier reparto entre ellas es equivalente; nunca se asocia por posición. Las
    actuaciones sin pareja en v2 se marcan `en_referencia=False` y no reciben identificador local.
    """
    huella = huella or (lambda a: a.huella_version)  # la referencia portable compara huellas con clave
    actuaciones = list(actuaciones)
    leidas = Counter(huella(a) for a in actuaciones)
    previas = Counter(h for _, h in referencia)
    faltantes = previas - leidas
    if faltantes:
        raise HistorialNoCorresponde("La lectura no contiene toda la línea base; no se conserva")
    libres = {}
    for local_id, h in referencia:
        libres.setdefault(h, deque()).append(local_id)
    items = []
    for indice, a in enumerate(actuaciones):
        cola = libres.get(huella(a))
        emparejada = bool(cola)
        local_id = cola.popleft() if cola else None  # la referencia portable no tiene local_id (None)
        # Presentación: solo se interpreta la descripción para mostrarla; la huella ya se calculó del contenido canónico.
        partes, legible, inesperado = presentar(a.descripcion)
        items.append({
            "indice": indice, "local_id": local_id, "en_referencia": emparejada,
            "fecha": a.fecha.isoformat(), "etapa": a.etapa, "origen": a.origen, "destino": a.destino,
            "remitente": a.remitente, "descripcion": legible, "secciones": partes, "formato_inesperado": inesperado,
            # Solo la descripción de cada anexo: nunca archivos ni referencias de descarga.
            "anexos": [{"descripcion": x.descripcion, "sin_enlace": bool(x.sin_enlace)} for x in a.anexos],
        })
    if sum(1 for i in items if i["en_referencia"]) != previas.total():
        raise HistorialNoCorresponde("Correspondencia inconsistente; no se conserva")
    return tuple(items)


class HistorialTemporal:
    """Una sola sesión a la vez, vigente hasta `vence` o hasta `invalidar()`. Seguro entre hilos."""

    def __init__(self, *, reloj=time.monotonic, temporizador=False):
        self._reloj, self._temporizador = reloj, temporizador
        self._lock = threading.Lock()
        self._sesion = None
        self._timer = None

    def cargar(self, caso, items, ttl_s=TTL_PREDETERMINADO_S):
        if type(ttl_s) is not int or not 60 <= ttl_s <= TTL_MAXIMO_S:
            raise ValueError("Duración de la sesión no permitida")
        if not isinstance(items, tuple) or not items:
            raise ValueError("Historial vacío")
        with self._lock:
            self._limpiar()
            self._sesion = _Sesion(str(uuid4()), caso, self._reloj() + ttl_s, items)
            if self._temporizador:
                self._timer = threading.Timer(ttl_s + 0.5, self.invalidar)
                self._timer.daemon = True
                self._timer.start()
            return {"sesion": self._sesion.sesion, "expira_en_s": ttl_s, "actuaciones": len(items)}

    def _limpiar(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._sesion = None

    def _vigente(self, caso=None):
        s = self._sesion
        if s is not None and self._reloj() >= s.vence:
            self._limpiar()
            return None
        return s if s is not None and (caso is None or s.caso == caso) else None

    def invalidar(self):
        with self._lock:
            self._limpiar()

    def estado(self):
        with self._lock:
            s = self._vigente()
            return {"activa": s is not None, "actuaciones": len(s.items) if s else 0,
                    "expira_en_s": max(0, int(s.vence - self._reloj())) if s else 0}

    def listado(self, caso):
        """Resumen con vista previa; el texto completo se obtiene por actuación en `detalle`."""
        with self._lock:
            s = self._vigente(caso)
            if s is None:
                return None
            return {"contrato_version": 1, "contenido": "temporal_en_memoria", "sesion": s.sesion,
                    "expira_en_s": max(0, int(s.vence - self._reloj())), "total": len(s.items),
                    "en_referencia": sum(1 for i in s.items if i["en_referencia"]),
                    "formato_inesperado": sum(1 for i in s.items if i["formato_inesperado"]),
                    "actuaciones": [{
                        "indice": i["indice"], "fecha": i["fecha"], "remitente": i["remitente"],
                        **dict(zip(("vista_previa", "truncada"), vista_previa(i["secciones"], VISTA_PREVIA))),
                        "anexos": len(i["anexos"]), "en_referencia": i["en_referencia"],
                        "formato_inesperado": i["formato_inesperado"],
                    } for i in s.items]}

    def detalle(self, caso, sesion, indice):
        with self._lock:
            s = self._vigente(caso)
            if s is None or s.sesion != sesion or type(indice) is not int or not 0 <= indice < len(s.items):
                return None
            return {"contrato_version": 1, "contenido": "temporal_en_memoria", "sesion": s.sesion,
                    "expira_en_s": max(0, int(s.vence - self._reloj())), **s.items[indice]}


def leer_con_referencia(cliente, usuario, clave, *, tipo, total_casos, caso_numero, politica, entradas, huella, caso,
                        historial, ttl_s=TTL_PREDETERMINADO_S, total_actuaciones=None, contenedor_id=None,
                        caso_login=None):
    """Núcleo común de la lectura: independiente de dónde venga la referencia (SQLite v2 o archivo portable).

    `entradas` = [(local_id|None, huella_comparable)] y `huella(actuacion)` produce la huella comparable. Con
    `total_casos=None` el listado se verifica solo estructuralmente (opción explícita del cliente), y el caso debe
    figurar exactamente una vez; la identidad del detalle y la contención de la referencia se mantienen siempre.
    """
    exigir_identidad_expediente(politica, caso_numero)
    if not entradas:
        raise HistorialNoCorresponde("No existe una línea base para este expediente")
    opciones = {"listado_estructural": True} if total_casos is None else {}
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login,
                               **opciones)
    if [c.numero for c in casos].count(caso_numero) != 1:
        raise HistorialNoCorresponde("El caso no figura exactamente una vez en el listado validado")
    lectura = leer_historial_validado(cliente, caso_numero, total_esperado=total_actuaciones, contenedor_id=contenedor_id)
    numero, actuaciones = _resolver_lectura(lectura)
    if numero != caso_numero:
        raise HistorialNoCorresponde("La lectura no corresponde al expediente acreditado")
    items = construir_items(actuaciones, entradas, huella)
    resumen = historial.cargar(caso, items, ttl_s)
    return {"lectura_real": True, "actuaciones": len(items), "en_referencia": len(entradas),
            "adicionales_a_la_referencia": len(items) - len(entradas), "expira_en_s": resumen["expira_en_s"],
            "persistencia": "solo_memoria", "linea_base_modificada": False, "notificaciones": "no_activadas",
            "transferencia_externa": "no_autorizada"}


def leer_historial_temporal(cliente, usuario, clave, *, tipo, total_casos, caso_numero, servicio, historial,
                            ttl_s=TTL_PREDETERMINADO_S, total_actuaciones=None, contenedor_id=None, caso_login=None):
    """UNA lectura manual local sobre la referencia SQLite v2 (solo lectura; no cambia la generación)."""
    if getattr(getattr(servicio, "almacen", None), "perfil", None) != "real":
        raise IdentidadExpedienteNoVerificada("Persistencia SIGAC bloqueada: se requiere el almacén real v2")
    politica = getattr(getattr(servicio, "observador", None), "politica", None)
    exigir_identidad_expediente(politica, caso_numero)  # antes de tocar la base
    caso = caso_local(caso_numero)
    return leer_con_referencia(
        cliente, usuario, clave, tipo=tipo, total_casos=total_casos, caso_numero=caso_numero, politica=politica,
        entradas=referencia_v2(servicio, caso), huella=lambda a: a.huella_version, caso=caso, historial=historial,
        ttl_s=ttl_s, total_actuaciones=total_actuaciones, contenedor_id=contenedor_id, caso_login=caso_login)
