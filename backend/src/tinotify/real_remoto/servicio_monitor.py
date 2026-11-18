"""Servicio del monitor: guarda las credenciales cifradas y ejecuta una revisión completa. Sin texto judicial en ningún punto."""

import json
import logging
import time

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.almacen import AlmacenNoDisponible
from tinotify.real_remoto.cifrado import (
    CifradoNoValido, VERSION_LLAVE, cifrar_credenciales, cifrar_expediente, descifrar_credenciales, descifrar_expediente)
from tinotify.real_remoto.monitor import caso_ref, clave_de_usuario, leer_expedientes, leer_un_expediente
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, SesionOcupada

registro = logging.getLogger("tinotify.real_remoto")
_ACCESO_RECHAZADO = {CodigoHistorial.AUTENTICACION_NO_CONFIRMADA, CodigoHistorial.SESION_NO_CONFIRMADA,
                     CodigoHistorial.ACCESO_INCOMPLETO}


CACHE_DETALLE_S = 300


class ExpedienteNoEncontrado(Exception):
    """El expediente no está en el listado guardado."""


class SinCredenciales(Exception):
    """No hay credenciales guardadas: hay que iniciar sesión desde la app con «recordar»."""


class ServicioMonitor:
    def __init__(self, *, config, almacen, sesiones, referencia, clave_acreditacion, fcm=None, usuario=None):
        self._config, self._almacen, self._sesiones, self._fcm = config, almacen, sesiones, fcm
        self._usuario = usuario  # None = propietario (con referencia acreditada); si no, un usuario (expedientes provisionales)
        self._referencia = referencia
        self._clave = clave_acreditacion if usuario is None else clave_de_usuario(clave_acreditacion, usuario)
        self._llave = config.monitor.clave_cifrado
        self._cache = {}  # caso_ref -> (instante, actuaciones): evita iniciar sesión en SIGAC por cada toque

    def guardar_credenciales(self, usuario, clave, caso_login=None):
        nonce, cifrado = cifrar_credenciales(self._llave, usuario, clave, caso_login)
        self._almacen.guardar_credenciales(VERSION_LLAVE, nonce, cifrado)

    def conectar(self, usuario_sigac, clave, caso_login=None):
        """Comprueba que SIGAC acepta las credenciales (un inicio de sesión) y SOLO entonces las guarda cifradas. Devuelve cuántos expedientes ve."""
        cfg = self._config
        opciones = {"listado_estructural": True} if cfg.total_casos is None else {}
        try:
            casos = self._sesiones.con_cliente(lambda cliente: cliente.autenticar(
                usuario_sigac, clave, tipo=cfg.tipo, total_casos_esperado=cfg.total_casos, caso_login=caso_login, **opciones))
            self.guardar_credenciales(usuario_sigac, clave, caso_login)
        finally:
            del usuario_sigac, clave, caso_login
        return len(casos)

    def registrar_dispositivo(self, token):
        self._almacen.registrar_dispositivo(token)

    def borrar_dispositivo(self, token):
        return self._almacen.borrar_dispositivo(token)

    def _notificar_push(self, plan, metadatos=None):
        """Un intento por aviso nuevo (el correo de Actions sigue siendo el respaldo con reintentos). Solo conteos: nunca radicados
        ni nombres, porque el texto se ve en la pantalla de bloqueo."""
        if self._fcm is None:
            return "no_configurado"
        cuerpo, pestana, expediente = _texto_push(plan, metadatos)
        datos = {"tipo": "novedades", "pestana": pestana, **({"expediente": expediente} if expediente else {})}
        # `privado`: en la pantalla de bloqueo con seguridad el teléfono oculta el texto (que ahora lleva el radicado) hasta desbloquear.
        enviados, invalidos, errores = self._enviar_a_dispositivos(cuerpo, datos, privado=True)
        return "enviado" if enviados else "fallido" if (invalidos or errores) else "sin_dispositivos"

    def enviar_prueba(self):
        """Notificación de prueba a los dispositivos registrados. No toca expedientes, avisos ni estado. (enviados, inválidos) o None sin FCM."""
        if self._fcm is None:
            return None
        enviados, invalidos, _ = self._enviar_a_dispositivos("Notificación de prueba: tu teléfono recibe los avisos de Tinotify.", {"tipo": "prueba", "pestana": "inicio"})
        return enviados, invalidos

    def _enviar_a_dispositivos(self, cuerpo, datos, privado=False):
        enviados = invalidos = errores = 0
        try:
            for token in self._almacen.dispositivos():
                resultado = self._fcm.enviar(token, "Tinotify", cuerpo, datos, privado)
                if resultado == "ok":
                    enviados += 1
                elif resultado == "token_invalido":
                    invalidos += 1
                    self._almacen.borrar_dispositivo(token)
                else:
                    errores += 1
        except AlmacenNoDisponible:
            registro.warning("push_sin_almacen")
            errores += 1
        return enviados, invalidos, errores

    # --- expedientes (listado cifrado) ---------------------------------------------------------------------------------
    def _guardar_expedientes(self, plan, metadatos):
        filas = []
        for cambio in plan.cambios:
            if cambio.caso_ref not in metadatos:
                continue
            numero, cliente, estado = metadatos[cambio.caso_ref]
            nonce, cifrado = cifrar_expediente(self._llave, cambio.caso_ref, numero, cliente, estado)
            sumar = cambio.novedades if cambio.accion == "novedades" else 0
            filas.append((cambio.caso_ref, VERSION_LLAVE, nonce, cifrado, sumar, cambio.accion == "nuevo" and not plan.primera_ejecucion))
        try:
            self._almacen.guardar_expedientes(filas)
        except AlmacenNoDisponible:
            registro.warning("expedientes_sin_almacen")  # el listado se reintenta en la próxima revisión

    def expedientes(self):
        salida = []
        for ref, version, nonce, cifrado, no_vistas, nuevo, ultima in self._almacen.expedientes():
            try:
                numero, cliente, estado = descifrar_expediente(self._llave, ref, nonce, cifrado)
            except CifradoNoValido:
                continue  # llave distinta o dato alterado: no se muestra
            salida.append({"id": ref, "numero": numero, "cliente": cliente, "estado": estado,
                           "novedades_no_vistas": no_vistas, "nuevo": nuevo, "ultima_novedad": ultima})
        salida.sort(key=lambda e: (-(e["novedades_no_vistas"] > 0), -e["numero"]))
        return salida

    def canal_aviso(self, aviso, canal, estado):
        return self._almacen.fijar_canal_aviso(aviso, canal, estado)

    def historial_expediente(self, caso_ref):
        """Actuaciones de UN expediente leídas de SIGAC en este momento (inicia sesión con las credenciales guardadas). No se guardan."""
        antes = time.monotonic()
        guardado = self._cache.get(caso_ref)
        if guardado and antes - guardado[0] < CACHE_DETALLE_S:
            return guardado[1]
        fila = next((f for f in self._almacen.expedientes() if f[0] == caso_ref), None)
        if fila is None:
            raise ExpedienteNoEncontrado
        try:
            numero, _, _ = descifrar_expediente(self._llave, caso_ref, fila[2], fila[3])
        except CifradoNoValido:
            raise ExpedienteNoEncontrado from None
        credenciales = self._almacen.credenciales()
        if credenciales is None:
            raise SinCredenciales
        usuario, clave, caso_login = descifrar_credenciales(self._llave, credenciales[1], credenciales[2])
        cfg = self._config
        try:
            actuaciones = self._sesiones.con_cliente(lambda cliente: leer_un_expediente(
                cliente, usuario, clave, tipo=cfg.tipo, total_casos=cfg.total_casos, caso_login=caso_login, numero=numero))
        finally:
            del usuario, clave, caso_login
        datos = [_actuacion_json(a) for a in sorted(actuaciones, key=lambda a: a.fecha, reverse=True)]
        self._cache[caso_ref] = (time.monotonic(), datos)
        return datos

    def marcar_vistos(self, caso_ref=None):
        return self._almacen.marcar_vistos(caso_ref)

    def olvidar_credenciales(self):
        return self._almacen.olvidar_credenciales()

    def estado(self):
        return self._almacen.estado()

    def ejecuciones(self, limite=30):
        return self._almacen.ejecuciones_recientes(limite)

    def avisos_pendientes(self):
        return self._almacen.avisos_pendientes()

    def marcar_entregado(self, aviso):
        return self._almacen.marcar_entregado(aviso)

    def _cerrar(self, ejecucion, resultado, **datos):
        try:
            self._almacen.cerrar_ejecucion(ejecucion, resultado, **datos)
        except AlmacenNoDisponible:
            pass  # el resultado ya se informa a quien llamó; no se oculta el error original

    def ejecutar(self):
        fila = self._almacen.credenciales()
        if fila is None:
            raise SinCredenciales
        usuario, clave, caso_login = descifrar_credenciales(self._llave, fila[1], fila[2])  # CifradoNoValido si la llave no coincide
        ejecucion = self._almacen.iniciar_ejecucion()
        cfg = self._config
        try:
            lecturas, fallidos, listados, errores, diagnosticos, metadatos = self._sesiones.con_cliente(lambda cliente: leer_expedientes(
                cliente, usuario, clave, tipo=cfg.tipo, total_casos=cfg.total_casos, caso_login=caso_login,
                clave_acreditacion=self._clave, instancia=INSTANCIA_REAL))
        except SesionOcupada:
            self._cerrar(ejecucion, "error_interno", codigo="sesion_ocupada")
            raise
        except DemasiadosIntentosLogin:
            self._cerrar(ejecucion, "error_interno", codigo="presupuesto_agotado")
            raise
        except SigacClientError as error:
            rechazado = isinstance(error, SigacSessionExpired) or error.codigo in _ACCESO_RECHAZADO
            self._cerrar(ejecucion, "error_acceso" if rechazado else "error_sigac", codigo=error.codigo.value[:64])
            raise
        finally:
            del usuario, clave, caso_login  # las credenciales no sobreviven a la lectura
        if errores:
            # Para quien opera el servicio: cuántos expedientes fallaron y con qué código/etapa de catálogo.
            registro.warning("monitor_casos_fallidos listados=%s leidos=%s detalle=%s", listados, len(lecturas), json.dumps(
                sorted([{"codigo": c, "etapa": e, "n": n} for (c, e), n in errores.items()], key=lambda d: (-d["n"], d["codigo"]))))
        if diagnosticos:
            registro.warning("monitor_diagnostico_anexos conteos=%s", json.dumps(diagnosticos, sort_keys=True))
        semillas = ({caso_ref(self._clave, INSTANCIA_REAL, self._referencia.numero): self._referencia.multiconjunto()}
                    if self._usuario is None else {})  # solo el propietario tiene un expediente acreditado
        try:
            plan, aviso = self._almacen.aplicar(lecturas, semillas)
        except AlmacenNoDisponible:
            self._cerrar(ejecucion, "error_estado")
            raise
        self._guardar_expedientes(plan, metadatos)
        if aviso:
            estado_push = self._notificar_push(plan, metadatos)
            try:
                self._almacen.fijar_canal_aviso(aviso, "push", estado_push)
            except AlmacenNoDisponible:
                registro.warning("canal_aviso_sin_almacen")
        self._cerrar(ejecucion, plan.resultado, expedientes=min(plan.expedientes, 1000), novedades=min(plan.novedades, 100000),
                     codigo="casos_fallidos" if fallidos else None)
        return {"resultado": plan.resultado, "expedientes": plan.expedientes, "novedades": plan.novedades,
                "expedientes_con_novedades": plan.expedientes_con_novedades, "expedientes_nuevos": plan.expedientes_nuevos,
                "anomalias": plan.anomalias, "casos_fallidos": fallidos, "linea_base": plan.primera_ejecucion,
                "aviso_nuevo": aviso, "avisos": self._almacen.avisos_pendientes()}


def _plural(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def _lista_radicados(numeros):
    numeros = [str(n) for n in numeros]
    return numeros[0] if len(numeros) == 1 else ", ".join(numeros[:-1]) + " y " + numeros[-1]


def _texto_push(plan, metadatos=None):
    """(texto, pestaña, expediente). Con `metadatos` el texto nombra los radicados (hasta tres); sin ellos, solo conteos.

    `expediente` es el identificador opaco del único expediente afectado (la app lo abre directamente al tocar el aviso)."""
    cambios = list(getattr(plan, "cambios", ()) or ())
    if metadatos and cambios:
        con_novedades = [(metadatos[c.caso_ref][0], c.novedades, c.caso_ref) for c in cambios
                         if c.accion == "novedades" and c.caso_ref in metadatos]
        nuevos = [(metadatos[c.caso_ref][0], c.caso_ref) for c in cambios
                  if c.accion == "nuevo" and not plan.primera_ejecucion and c.caso_ref in metadatos]
        partes = []
        if con_novedades:
            total = sum(n for _, n, _ in con_novedades)
            donde = (f"el radicado {con_novedades[0][0]}" if len(con_novedades) == 1 else
                     f"los radicados {_lista_radicados([x[0] for x in con_novedades])}" if len(con_novedades) <= 3 else
                     f"{len(con_novedades)} expedientes")
            partes.append(f"{_plural(total, 'actuación nueva', 'actuaciones nuevas')} en {donde}")
        if nuevos:
            partes.append(f"Expediente nuevo: {nuevos[0][0]}" if len(nuevos) == 1 else f"{len(nuevos)} expedientes nuevos")
        if partes:
            unico = (con_novedades[0][2] if len(con_novedades) == 1 and not nuevos else nuevos[0][1] if len(nuevos) == 1 and not con_novedades else None)
            return " · ".join(partes), "casos", unico
    if plan.novedades:
        texto = f"{_plural(plan.novedades, 'actuación nueva', 'actuaciones nuevas')} en {_plural(plan.expedientes_con_novedades, 'expediente', 'expedientes')}"
        if plan.expedientes_nuevos:
            texto += f" y {_plural(plan.expedientes_nuevos, 'expediente nuevo', 'expedientes nuevos')}"
        return texto, "casos", None
    if plan.expedientes_nuevos:
        return ("Apareció un expediente nuevo en tu cuenta" if plan.expedientes_nuevos == 1
                else f"Aparecieron {plan.expedientes_nuevos} expedientes nuevos en tu cuenta"), "casos", None
    return "Una lectura necesita tu revisión en SIGAC", "actividad", None


def _actuacion_json(a):
    return {"fecha": a.fecha.isoformat(), "etapa": a.etapa, "origen": a.origen, "destino": a.destino, "remitente": a.remitente,
            "descripcion": a.descripcion[:20000],
            "anexos": [{"descripcion": x.descripcion, "archivo": x.archivo, "sin_enlace": x.sin_enlace} for x in a.anexos]}


class ServiciosMonitor:
    """Un ServicioMonitor por usuario (None = propietario), sobre una vista del almacén ligada a ese usuario. Comparten el gestor de
    sesiones SIGAC: solo hay una sesión en curso a la vez y un presupuesto común de inicios de sesión."""

    def __init__(self, *, config, almacen, sesiones, referencia, clave_acreditacion, fcm=None):
        self._raiz = almacen
        self._args = dict(config=config, sesiones=sesiones, referencia=referencia, clave_acreditacion=clave_acreditacion, fcm=fcm)
        self._cache = {}
        self.resolver_correo = None  # función usuario_id -> correo; la fija la aplicación si hay cuentas

    def para(self, usuario=None):
        if usuario not in self._cache:
            self._cache[usuario] = ServicioMonitor(almacen=self._raiz.de(usuario), usuario=usuario, **self._args)
        return self._cache[usuario]

    def usuarios(self):
        return {"propietario": self._raiz.de(None).credenciales() is not None, "usuarios": self._raiz.usuarios_con_credenciales()}

    def avisos_pendientes_todos(self):
        """Avisos pendientes de todos para el ciclo de Actions. Los de un usuario llevan `destino` (su correo, descifrado solo aquí);
        los del propietario no: Actions usa el correo configurado como secreto."""
        avisos = self._raiz.avisos_pendientes_todos()
        for a in avisos:
            if a.get("usuario") and self.resolver_correo is not None:
                correo = self.resolver_correo(a["usuario"])
                if correo:
                    a["destino"] = correo
        # Detalle para el correo: los expedientes con novedades sin ver de cada dueño, en su aviso MÁS RECIENTE (así no se repite la lista).
        ultimos = {}
        for a in avisos:
            ultimos[a.get("usuario")] = a
        for dueno, a in ultimos.items():
            try:
                a["expedientes"] = [{"numero": x["numero"], "cliente": x["cliente"], "estado": x["estado"],
                                     "novedades": x["novedades_no_vistas"], "nuevo": x["nuevo"]}
                                    for x in self.para(dueno).expedientes() if x["novedades_no_vistas"] or x["nuevo"]][:20]
            except Exception:  # noqa: BLE001 - el detalle es opcional: sin él el correo sale con conteos
                pass
        return avisos
