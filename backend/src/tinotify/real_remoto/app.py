"""ASGI del backend remoto real:

    uvicorn tinotify.real_remoto.app:crear_app --factory --workers 1 --no-proxy-headers --no-access-log

`--workers 1` es obligatorio (el historial vive en memoria del proceso) y `--no-proxy-headers` también: la política
de proxy confiable es la de esta aplicación. No tiene base de datos ni escribe en disco. Las credenciales SIGAC
llegan solo en el cuerpo de `POST /real/sesion` por HTTPS, se usan en memoria y se descartan; nunca se registran.
"""

from contextlib import asynccontextmanager
import json
import hashlib
import logging
import platform
import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.comun import Acceso, evaluar_transporte, respuesta as _respuesta
from tinotify.real_remoto.almacen import AlmacenIncompatible, AlmacenNoDisponible, AlmacenPg
from tinotify.real_remoto.cifrado import CifradoNoValido
from tinotify.real_remoto.config import Config, ConfiguracionInsegura
from tinotify.real_remoto.fcm import ClienteFcm, CuentaServicioNoValida
from tinotify.real_remoto.rutas_cuentas import registrar_cuentas
from tinotify.real_remoto.rutas_monitor import registrar_monitor
from tinotify.real_remoto.servicio_cuentas import ServicioCuentas
from tinotify.real_remoto.servicio_monitor import ServicioMonitor, ServiciosMonitor
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, GestorSesion, SesionOcupada
from tinotify.services import referencia_portable
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
from tinotify.services.historial_temporal import HistorialNoCorresponde, HistorialTemporal
from tinotify.services.politica_real_local import cargar_clave_acreditacion, politica_desde_clave

registro = logging.getLogger("tinotify.real_remoto")
_RECHAZOS_REGISTRADOS = {"n": 0}
RUTAS_SIN_AUTENTICACION = ("/health", "/abrir")
_INTENT = "intent://abrir#Intent;scheme=tinotify;package=com.tinotify.app;end"
PAGINA_ABRIR = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Abrir Tinotify</title><style>body{{font-family:system-ui,sans-serif;background:#D9E4F4;color:#14213D;margin:0;padding:32px 20px;text-align:center}}
a.b{{display:inline-block;background:#14213D;color:#fff;text-decoration:none;font-weight:700;padding:14px 28px;border-radius:999px;margin-top:16px}}p{{color:#52627C}}</style></head>
<body><h1>Tinotify</h1><p>Abriendo la aplicación…</p><a class="b" href="{_INTENT}">Abrir Tinotify</a>
<p>Si no se abre, instala Tinotify en tu teléfono Android o ábrela desde el menú de aplicaciones.</p>
<script>setTimeout(function(){{location.href="{_INTENT}"}},300)</script></body></html>"""
MAX_CUERPO_LOGIN = 2048
# Fallos que significan «SIGAC no aceptó el acceso» frente a «SIGAC no respondió como se esperaba».
_ACCESO_RECHAZADO = {CodigoHistorial.AUTENTICACION_NO_CONFIRMADA, CodigoHistorial.SESION_NO_CONFIRMADA,
                     CodigoHistorial.ACCESO_INCOMPLETO}


class InicioSesion(BaseModel):
    """Secretos como `SecretStr`: no aparecen en repr, logs ni mensajes de validación."""

    model_config = ConfigDict(extra="forbid")
    usuario: SecretStr = Field(min_length=1, max_length=128)
    clave: SecretStr = Field(min_length=1, max_length=256)
    caso_login: SecretStr | None = Field(default=None, max_length=128)
    recordar: bool = False  # guardar las credenciales CIFRADAS para que el monitor pueda volver a entrar


def _http_desde_sigac(error):
    """HTTPException genérica para un fallo de SIGAC. Diagnóstico para quien opera el servicio: solo valores de catálogos
    cerrados (código, etapa y, si hubo un fallo de transporte, el NOMBRE de la clase de la excepción). Nunca mensajes, URLs,
    cabeceras ni credenciales."""
    causa = getattr(error, "causa", None)
    registro.warning("sigac_fallo codigo=%s etapa=%s causa=%s", error.codigo.value, error.etapa.value,
                     json.dumps(causa, sort_keys=True) if isinstance(causa, dict) else causa)
    if isinstance(error, SigacSessionExpired) or error.codigo in _ACCESO_RECHAZADO:
        return HTTPException(403, "Acceso no confirmado")
    return HTTPException(502, "El servicio institucional no respondió como se esperaba")


def _preparar(config, politica, referencia):
    if politica is None or referencia is None:
        try:
            clave = cargar_clave_acreditacion(config.acreditacion)
            politica = politica or politica_desde_clave(clave)
            referencia = referencia or referencia_portable.cargar(config.referencia, clave, instancia=INSTANCIA_REAL)
        except (IdentidadExpedienteNoVerificada, referencia_portable.ReferenciaPortableInvalida):
            raise ConfiguracionInsegura("acreditacion_o_referencia_invalida") from None
    try:
        politica.exigir_expediente(referencia.numero, INSTANCIA_REAL)
    except Exception:
        raise ConfiguracionInsegura("expediente_no_acreditado") from None
    return politica, referencia


def crear_app(config: Config | None = None, *, politica=None, referencia=None, historial=None,
              fabrica_cliente=SigacClient, reloj=time.monotonic, almacen=None, clave_acreditacion=None, almacen_cuentas=None, correo_cliente=None):
    config = config or Config.desde_entorno()  # el proceso no arranca con una configuración insegura
    politica, referencia = _preparar(config, politica, referencia)
    historial = historial or HistorialTemporal(reloj=reloj, temporizador=True)
    gestor = GestorSesion(config=config, politica=politica, referencia=referencia, historial=historial,
                          fabrica_cliente=fabrica_cliente, reloj=reloj)
    acceso = Acceso(config.token, reloj=reloj)
    servicio_monitor = servicio_cuentas = servicios = None
    if config.monitor is not None:
        if clave_acreditacion is None:
            try:
                clave_acreditacion = cargar_clave_acreditacion(config.acreditacion)
            except IdentidadExpedienteNoVerificada:
                raise ConfiguracionInsegura("acreditacion_o_referencia_invalida") from None
        almacen = almacen or AlmacenPg(config.monitor.pg)
        try:
            almacen.verificar()
        except AlmacenNoDisponible:
            registro.warning("almacen_no_disponible_al_arrancar")  # el servicio arranca; las rutas del monitor darán 503 hasta que responda
        except AlmacenIncompatible:
            raise ConfiguracionInsegura("almacen_incompatible") from None
        fcm = None
        if config.fcm_cuenta is not None:
            try:
                fcm = ClienteFcm(config.fcm_cuenta)
            except CuentaServicioNoValida:
                raise ConfiguracionInsegura("fcm_cuenta_no_valida") from None
        servicios = ServiciosMonitor(config=config, almacen=almacen, sesiones=gestor, referencia=referencia,
                                     clave_acreditacion=clave_acreditacion, fcm=fcm)
        servicio_monitor = servicios.para(None)
        if config.cuentas:
            from tinotify.real_remoto.almacen_cuentas import AlmacenCuentasPg  # carga perezosa: solo si las cuentas están activas
            llave_cuentas = hashlib.sha256(b"tinotify-cuentas|" + config.monitor.clave_cifrado).digest()
            llave_correo = hashlib.sha256(b"tinotify-correo|" + config.monitor.clave_cifrado).digest()
            if correo_cliente is None and config.correo_api is not None:
                from tinotify.real_remoto.correo_brevo import ClienteBrevo
                correo_cliente = ClienteBrevo(*config.correo_api)
            servicio_cuentas = ServicioCuentas(almacen_cuentas or AlmacenCuentasPg(config.monitor.pg), llave_cuentas, llave_correo=llave_correo,
                                               correo=correo_cliente)
            servicios.resolver_correo = servicio_cuentas.correo_de
    for biblioteca in ("httpx", "httpcore"):
        logging.getLogger(biblioteca).setLevel(logging.CRITICAL)  # sus mensajes incluyen URLs institucionales

    @asynccontextmanager
    async def ciclo_de_vida(app):
        registro.warning("arranque python=%s", platform.python_version())  # versión del intérprete (ayuda a diagnosticar)
        yield
        historial.invalidar()  # al apagar no queda contenido en memoria

    app = FastAPI(title="Tinotify real remoto", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def transporte(request: Request, siguiente):
        if request.url.path not in RUTAS_SIN_AUTENTICACION:
            par = request.client.host if request.client else None
            rechazo = evaluar_transporte(config, par, request.url.scheme, request.headers)
            if rechazo is not None:
                # Diagnóstico de despliegue (p. ej. si el proxy de Render no cae en las redes confiables). Solo la IP del
                # par TCP y la presencia de la cabecera, nunca valores de cabeceras; limitado para no inundar los logs.
                _RECHAZOS_REGISTRADOS["n"] += 1
                if _RECHAZOS_REGISTRADOS["n"] <= 20 or _RECHAZOS_REGISTRADOS["n"] % 500 == 0:
                    registro.warning("transporte_rechazado codigo=%s par=%s x_forwarded_proto=%s", rechazo[0], par,
                                     "x-forwarded-proto" in request.headers)
                return _respuesta(*rechazo)
            if "origin" in request.headers:  # solo clientes nativos: ningún navegador (CSRF/drive-by)
                return _respuesta(403, "Origen no permitido")
            if request.method == "POST":
                declarada = request.headers.get("content-length")
                if declarada is None and request.url.path != "/real/sesion":
                    declarada = "0"  # los POST sin cuerpo (p. ej. del monitor) pueden omitir la cabecera
                try:
                    longitud = int(declarada if declarada is not None else "")
                except ValueError:
                    return _respuesta(411, "Se requiere la longitud del cuerpo")
                if not 0 <= longitud <= MAX_CUERPO_LOGIN:
                    return _respuesta(413, "Cuerpo demasiado grande")
        respuesta = await siguiente(request)
        respuesta.headers["Cache-Control"] = "no-store"
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        if config.remoto:
            respuesta.headers["Strict-Transport-Security"] = "max-age=31536000"
        return respuesta

    @app.exception_handler(RequestValidationError)
    async def _validacion(request, error):
        return _respuesta(422, "Entrada no valida")  # sin eco de la entrada: puede contener credenciales

    @app.exception_handler(HTTPException)
    async def _http(request, error):
        return _respuesta(error.status_code, error.detail if isinstance(error.detail, str) else "Error",
                          **(error.headers or {}))

    @app.exception_handler(Exception)
    async def _interno(request, error):
        registro.error("error_interno tipo=%s", type(error).__name__)  # nunca el mensaje, la ruta ni el contenido
        return _respuesta(500, "Error interno")

    bearer = HTTPBearer(auto_error=False)

    def servicio_actual(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        """Quién llama: un usuario (token tn_...) o el propietario (token de la app). Devuelve SU servicio: cada uno ve solo sus datos."""
        token = credencial.credentials if credencial else None
        if servicio_cuentas is not None and token and token.startswith("tn_"):
            usuario = servicio_cuentas.autenticar(token)
            if usuario is not None:
                return servicios.para(usuario.id)
        resultado = acceso.comprobar(token)
        if resultado is True:
            return servicios.para(None)
        if resultado is None:
            raise HTTPException(429, "Demasiados intentos")
        raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})

    def autorizar(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        resultado = acceso.comprobar(credencial.credentials if credencial else None)
        if resultado is True:
            return
        if resultado is None:
            raise HTTPException(429, "Demasiados intentos")
        raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})

    protegidas = [Depends(autorizar)]

    @app.get("/abrir", response_class=HTMLResponse)
    async def abrir_app():
        """Página estática y pública a la que apuntan los botones de los correos: intenta abrir la app Tinotify. No lleva ni recibe datos."""
        return HTMLResponse(PAGINA_ABRIR, headers={"X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"})

    @app.get("/health")
    async def salud():
        return {"status": "ok"}

    @app.post("/real/sesion", dependencies=protegidas)
    async def iniciar_sesion(datos: InicioSesion):
        if datos.recordar and servicio_monitor is None:
            raise HTTPException(422, "Guardar credenciales no está disponible")
        usuario, clave = datos.usuario.get_secret_value(), datos.clave.get_secret_value()
        caso_login = datos.caso_login.get_secret_value() if datos.caso_login else None

        def iniciar_y_guardar():
            resumen = gestor.iniciar(usuario, clave, caso_login)
            guardadas = False
            if datos.recordar:
                try:
                    servicio_monitor.guardar_credenciales(usuario, clave, caso_login)
                    guardadas = True
                except (AlmacenNoDisponible, AlmacenIncompatible, CifradoNoValido):
                    registro.warning("credenciales_no_guardadas")  # el acceso ya funcionó: se informa, no se pierde la sesión
            return resumen, guardadas
        try:
            resumen, guardadas = await run_in_threadpool(iniciar_y_guardar)
        except SesionOcupada:
            raise HTTPException(409, "Ya hay un acceso en curso") from None
        except DemasiadosIntentosLogin as error:
            raise HTTPException(429, "Demasiados intentos de acceso; espera", headers={"Retry-After": str(error.espera_s)}) from None
        except HistorialNoCorresponde:
            raise HTTPException(422, "La lectura no corresponde a la referencia acreditada") from None
        except IdentidadExpedienteNoVerificada:
            raise HTTPException(503, "Servicio no configurado") from None
        except SigacClientError as error:
            raise _http_desde_sigac(error) from None
        respuesta = {"estado": "activa", "expira_en_s": resumen["expira_en_s"], "actuaciones": resumen["actuaciones"],
                     "en_referencia": resumen["en_referencia"], "adicionales": resumen["adicionales_a_la_referencia"]}
        if datos.recordar:
            respuesta["credenciales_guardadas"] = guardadas
        return respuesta

    @app.get("/real/sesion/estado", dependencies=protegidas)
    async def estado():
        return historial.estado()

    @app.delete("/real/sesion", dependencies=protegidas)
    async def cerrar_sesion():
        historial.invalidar()
        return {"activa": False}

    @app.get("/real/cases", dependencies=protegidas)
    async def casos():
        return [referencia.resumen_caso()]

    @app.get("/real/observaciones", dependencies=protegidas)
    async def observaciones():
        # Este backend no observa ni persiste cambios: no hay observaciones registradas (y no acredita ausencia).
        return {"contrato_version": 1, "cobertura": "desconocida", "referencia": "ocurrencias_observadas",
                "entrega_externa": "no_autorizada", "observaciones": []}

    @app.get("/real/cases/{caso}/historial", dependencies=protegidas)
    async def historial_real(caso: UUID):
        datos = historial.listado(str(caso)) if str(caso) == referencia.caso_id else None
        if datos is None:
            raise HTTPException(404, "Sin historial temporal activo para este expediente")
        return datos

    @app.get("/real/cases/{caso}/historial/{indice}", dependencies=protegidas)
    async def actuacion_real(caso: UUID, indice: int, sesion: UUID):
        datos = historial.detalle(str(caso), str(sesion), indice) if str(caso) == referencia.caso_id else None
        if datos is None:
            raise HTTPException(404, "Sin historial temporal activo para este expediente")
        return datos

    if servicio_cuentas is not None:
        registrar_cuentas(app, servicio=servicio_cuentas, protegidas_app=protegidas, reloj=reloj)
    if servicio_monitor is not None:
        registrar_monitor(app, servicios=servicios, servicio_actual=servicio_actual, config=config, protegidas_app=protegidas,
                          http_desde_sigac=_http_desde_sigac, reloj=reloj)
    return app
