"""Monitor real: lectura de TODOS los expedientes accesibles y comparación contra el estado guardado.

Solo se compara y se guarda lo mínimo: por expediente, el multiconjunto de huellas CON CLAVE (HMAC) de sus actuaciones y unos
conteos. Nunca se conserva texto judicial. La lógica de comparación (`planificar`) es una función pura, sin red ni base de datos.

Reglas:
- Sin estado previo en absoluto (primera ejecución): línea base silenciosa para todos los expedientes, salvo el acreditado, que
  parte de la referencia portable (todo lo posterior a esa referencia SÍ es novedad).
- Expediente nuevo en ejecuciones posteriores: se registra su línea base (sus actuaciones antiguas NO son novedades) y se avisa solo de
  que apareció un expediente.
- Novedad = huellas actuales menos huellas previas (con multiplicidad). Si falta alguna huella previa, la lectura es dudosa: no se
  notifican novedades ni se sobrescribe el estado; se marca una anomalía (avisada solo al producirse).
- Un expediente que deja de aparecer en el listado no cambia nada.
"""

from collections import Counter
from dataclasses import dataclass, field
import json
import hashlib
import hmac

from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, leer_historial_validado
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.integrations.sigac.sigac_perfil import RUTA_BANNER, extraer_nombre
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.services.referencia_portable import _sub, huella_portable

MAX_EXPEDIENTES = 200
MAX_DIAGNOSTICOS = 3  # relecturas diagnósticas por ejecución (solo conteos estructurales)


def caso_ref(clave_acreditacion, instancia, numero):
    """Identificador opaco (HMAC-SHA256, 64 hex) del expediente. No permite recuperar el número sin la clave."""
    return hmac.new(_sub(clave_acreditacion, "monitor-caso"), f"{instancia}|{numero}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class EstadoPrevio:
    huellas: Counter
    acreditado: bool = False
    generacion: int = 1
    anomalia: bool = False


@dataclass(frozen=True)
class Cambio:
    caso_ref: str
    accion: str            # nuevo | sin_cambios | novedades | anomalia
    huellas: Counter       # estado a conservar tras aplicar (el previo si es anomalía)
    novedades: int
    acreditado: bool
    generacion: int
    anomalia: bool
    en_bd: bool            # False: hay que insertar el expediente completo
    nuevas: Counter = field(default_factory=Counter)  # huellas nuevas (solo en `novedades`)


@dataclass(frozen=True)
class Plan:
    cambios: tuple
    expedientes: int
    novedades: int
    expedientes_con_novedades: int
    expedientes_nuevos: int
    anomalias: int
    primera_ejecucion: bool

    @property
    def requiere_aviso(self):
        return self.novedades > 0 or self.expedientes_nuevos > 0 or self.anomalias > 0

    @property
    def resultado(self):
        if self.anomalias:
            return "anomalia"
        return "linea_base" if self.primera_ejecucion and not self.novedades else "ok"


def planificar(previos, lecturas, semillas=None):
    """`previos`: {caso_ref: EstadoPrevio} de la base; `lecturas`: {caso_ref: Counter}; `semillas`: {caso_ref: Counter} del
    expediente acreditado (solo cuentan si no hay NINGÚN estado previo)."""
    semillas = semillas or {}
    primera = not previos
    efectivos = dict(previos)
    if primera:
        for ref, huellas in semillas.items():
            efectivos[ref] = EstadoPrevio(huellas=Counter(huellas), acreditado=True)
    cambios, novedades, con_novedades, nuevos, anomalias = [], 0, 0, 0, 0
    for ref in sorted(lecturas):
        actual = Counter(lecturas[ref])
        previo = efectivos.get(ref)
        en_bd = ref in previos
        if previo is None:
            cambios.append(Cambio(ref, "nuevo", actual, 0, False, 1, False, False))
            if not primera:
                nuevos += 1
            continue
        faltantes, nuevas = previo.huellas - actual, actual - previo.huellas
        if faltantes:
            if not previo.anomalia:
                anomalias += 1  # solo al producirse: una anomalía persistente no repite el aviso
            cambios.append(Cambio(ref, "anomalia", Counter(previo.huellas), 0, previo.acreditado, previo.generacion, True, en_bd))
        elif nuevas:
            n = nuevas.total()
            novedades += n
            con_novedades += 1
            cambios.append(Cambio(ref, "novedades", actual, n, previo.acreditado, previo.generacion + 1, False, en_bd, Counter(nuevas)))
        else:
            cambios.append(Cambio(ref, "sin_cambios", actual, 0, previo.acreditado, previo.generacion, False, en_bd))
    return Plan(tuple(cambios), len(lecturas), novedades, con_novedades, nuevos, anomalias, primera)


def ficha_de(a):
    """Datos mínimos de una actuación para el feed de Novedades (se guardan CIFRADOS): fecha, etapa, sentido y un extracto corto."""
    return {"fecha": a.fecha.isoformat(), "etapa": a.etapa[:160], "origen": a.origen[:60], "destino": a.destino[:60],
            "remitente": a.remitente[:160], "resumen": _extracto(a.descripcion), "anexos": len(a.anexos)}


def _extracto(descripcion, largo=240):
    texto = descripcion
    if texto.startswith("TINOTIFY_FILAS_V1:"):
        try:
            filas = json.loads(texto[len("TINOTIFY_FILAS_V1:"):])["filas"]
            texto = " · ".join(f"{f[0]}: {f[1]}" for f in filas)
        except (ValueError, KeyError, IndexError, TypeError):
            pass
    texto = " ".join(texto.split())
    return texto if len(texto) <= largo else texto[:largo - 1].rstrip() + "…"


def leer_expedientes(cliente, usuario, clave, *, tipo, total_casos, caso_login, clave_acreditacion, instancia,
                     max_expedientes=MAX_EXPEDIENTES, fichas=None):
    """Una autenticación y una lectura validada por expediente. Devuelve ({caso_ref: Counter}, fallidos, listados, errores, diagnosticos, metadatos) con `errores` = conteo por (código, etapa) y `diagnosticos` = conteos estructurales de hasta MAX_DIAGNOSTICOS relecturas.

    Un expediente que falla (salvo por sesión caducada, que aborta todo) se omite y su estado no cambia. Un historial vacío es un
    estado válido (así su primera actuación sí será novedad)."""
    opciones = {"listado_estructural": True} if total_casos is None else {}
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login, **opciones)
    if len(casos) > max_expedientes:
        raise SigacClientError("Demasiados expedientes.", codigo=CodigoHistorial.LISTADO_NO_CONFIRMADO)
    lecturas, fallidos, errores, diagnosticos, metadatos = {}, 0, Counter(), [], {}
    for caso in casos:
        ref = caso_ref(clave_acreditacion, instancia, caso.numero)
        metadatos[ref] = (caso.numero, caso.cliente, caso.estado)  # del listado de SIGAC; se guardan CIFRADOS
        try:
            _, actuaciones = _resolver_lectura(leer_historial_validado(cliente, caso.numero))
            huellas = [(huella_portable(clave_acreditacion, a.huella_version), a) for a in actuaciones]
            lecturas[ref] = Counter(h for h, _ in huellas)
            if fichas is not None:
                fichas[ref] = {h: ficha_de(a) for h, a in huellas}  # en memoria: solo se guardan (cifradas) las de las novedades
        except SigacSessionExpired:
            raise
        except SigacClientError as error:
            if error.codigo is CodigoHistorial.SIN_ACTUACIONES:
                lecturas[ref] = Counter()
            else:
                fallidos += 1
                # Solo valores de catálogos cerrados (código y etapa): ni números de caso ni contenido.
                errores[(error.codigo.value, error.etapa.value)] += 1
                if error.codigo is CodigoHistorial.ANEXO_ENLACE_AUSENTE and len(diagnosticos) < MAX_DIAGNOSTICOS:
                    # Una relectura con diagnóstico devuelve SOLO conteos estructurales en lista blanca (diagnostico_seguro):
                    # sin texto, atributos, URLs ni números de caso. Sirve para saber por qué se rechaza el anexo.
                    try:
                        cliente.consultar_historial(caso.numero, diagnostico=True)
                    except SigacClientError as segundo:
                        if isinstance(segundo.diagnostico, dict):
                            diagnosticos.append(segundo.diagnostico.get("estadisticas_estructurales", {}))
    return lecturas, fallidos, len(casos), errores, diagnosticos, metadatos


def leer_un_expediente(cliente, usuario, clave, *, tipo, total_casos, caso_login, numero):
    """Una autenticación y la lectura validada de UN expediente (bajo demanda). Devuelve sus actuaciones; un historial vacío es válido."""
    opciones = {"listado_estructural": True} if total_casos is None else {}
    cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login, **opciones)
    try:
        _, actuaciones = _resolver_lectura(leer_historial_validado(cliente, numero))
    except SigacClientError as error:
        if error.codigo is CodigoHistorial.SIN_ACTUACIONES:
            return []
        raise
    return actuaciones


def leer_nombre(cliente, usuario, clave, *, tipo, total_casos, caso_login):
    """Una autenticación y una lectura del banner de SIGAC. Devuelve el nombre de quien inició sesión o None."""
    opciones = {"listado_estructural": True} if total_casos is None else {}
    cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login, **opciones)
    try:
        return extraer_nombre(cliente.obtener_html(RUTA_BANNER))
    except SigacClientError:
        return None  # el nombre es opcional: un fallo aquí no es un fallo de acceso


def clave_de_usuario(clave_acreditacion, usuario):
    """Clave propia de cada usuario para huellas y caso_ref: dos personas con el mismo expediente no se correlacionan."""
    return hashlib.sha256(b"tinotify-usuario|" + usuario.encode("ascii") + b"|" + bytes(clave_acreditacion)).digest()


def descargar_un_anexo(cliente, usuario, clave, *, tipo, total_casos, caso_login, numero, referencia):
    """Inicia sesión, abre el expediente (como lo haría el navegador) y descarga UN anexo. Devuelve (contenido, tipo, nombre)."""
    opciones = {"listado_estructural": True} if total_casos is None else {}
    cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login, **opciones)
    try:
        _resolver_lectura(leer_historial_validado(cliente, numero))  # abrir el caso fija el contexto de la sesión
    except SigacClientError as error:
        if error.codigo is not CodigoHistorial.SIN_ACTUACIONES:
            raise
    return cliente.descargar_anexo(referencia)
