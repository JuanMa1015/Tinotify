"""ASGI del backend remoto real:

    uvicorn tinotify.real_remoto.app:crear_app --factory --workers 1 --no-proxy-headers --no-access-log

`--workers 1` es obligatorio (el historial vive en memoria del proceso) y `--no-proxy-headers` también: la política
de proxy confiable es la de esta aplicación. No tiene base de datos ni escribe en disco. Las credenciales SIGAC
llegan solo en el cuerpo de `POST /real/sesion` por HTTPS, se usan en memoria y se descartan; nunca se registran.
"""

from contextlib import asynccontextmanager
import json
import logging
import platform
import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.real_remoto.comun import Acceso, evaluar_transporte, respuesta as _respuesta
from tinotify.real_remoto.config import Config, ConfiguracionInsegura
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, GestorSesion, SesionOcupada
from tinotify.services import referencia_portable
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
from tinotify.services.historial_temporal import HistorialNoCorresponde, HistorialTemporal
from tinotify.services.politica_real_local import cargar_clave_acreditacion, politica_desde_clave

registro = logging.getLogger("tinotify.real_remoto")
_RECHAZOS_REGISTRADOS = {"n": 0}
RUTAS_SIN_AUTENTICACION = ("/health",)
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
              fabrica_cliente=SigacClient, reloj=time.monotonic):
    config = config or Config.desde_entorno()  # el proceso no arranca con una configuración insegura
    politica, referencia = _preparar(config, politica, referencia)
    historial = historial or HistorialTemporal(reloj=reloj, temporizador=True)
    gestor = GestorSesion(config=config, politica=politica, referencia=referencia, historial=historial,
                          fabrica_cliente=fabrica_cliente, reloj=reloj)
    acceso = Acceso(config.token, reloj=reloj)
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
                try:
                    longitud = int(request.headers.get("content-length", ""))
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

    def autorizar(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        resultado = acceso.comprobar(credencial.credentials if credencial else None)
        if resultado is True:
            return
        if resultado is None:
            raise HTTPException(429, "Demasiados intentos")
        raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})

    protegidas = [Depends(autorizar)]

    @app.get("/health")
    async def salud():
        return {"status": "ok"}

    @app.post("/real/sesion", dependencies=protegidas)
    async def iniciar_sesion(datos: InicioSesion):
        try:
            resumen = await run_in_threadpool(
                gestor.iniciar, datos.usuario.get_secret_value(), datos.clave.get_secret_value(),
                datos.caso_login.get_secret_value() if datos.caso_login else None)
        except SesionOcupada:
            raise HTTPException(409, "Ya hay un acceso en curso") from None
        except DemasiadosIntentosLogin as error:
            raise HTTPException(429, "Demasiados intentos de acceso; espera", headers={"Retry-After": str(error.espera_s)}) from None
        except HistorialNoCorresponde:
            raise HTTPException(422, "La lectura no corresponde a la referencia acreditada") from None
        except IdentidadExpedienteNoVerificada:
            raise HTTPException(503, "Servicio no configurado") from None
        except SigacClientError as error:
            # Diagnóstico para quien opera el servicio: solo valores de catálogos cerrados (código, etapa y, si hubo un fallo
            # de transporte, el NOMBRE de la clase de la excepción). Nunca mensajes, URLs, cabeceras ni credenciales.
            causa = getattr(error, "causa", None)
            registro.warning("sigac_fallo codigo=%s etapa=%s causa=%s", error.codigo.value, error.etapa.value,
                             json.dumps(causa, sort_keys=True) if isinstance(causa, dict) else causa)
            if isinstance(error, SigacSessionExpired) or error.codigo in _ACCESO_RECHAZADO:
                raise HTTPException(403, "Acceso no confirmado") from None
            raise HTTPException(502, "El servicio institucional no respondió como se esperaba") from None
        return {"estado": "activa", "expira_en_s": resumen["expira_en_s"], "actuaciones": resumen["actuaciones"],
                "en_referencia": resumen["en_referencia"], "adicionales": resumen["adicionales_a_la_referencia"]}

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

    return app
