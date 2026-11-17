"""ASGI opt-in: uvicorn tinotify.api.demo:crear_app --factory. Solo datos ficticios."""

from contextlib import asynccontextmanager
import os
import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from tinotify.demo.catalogo import CatalogoSintetico
from tinotify.demo.push import ExpoPush
from tinotify.api.real_local import AccesoLocal, DemasiadosIntentos, registrar_rutas_reales
from tinotify.demo.novedades import INSTANCIA_REAL, ServicioNovedadesLocal
from tinotify.demo.servicio import AccesoDemo, ConflictoDemo, ServicioDemo
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, AlmacenSqliteLocal


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Acceso(Entrada):
    codigo: SecretStr = Field(min_length=24, max_length=128)


class Dispositivo(Entrada):
    token: SecretStr

    @field_validator("token")
    @classmethod
    def token_valido(cls, valor):
        if not re.fullmatch(r"(ExpoPushToken|ExponentPushToken)\[[A-Za-z0-9_-]{8,256}\]", valor.get_secret_value()):
            raise ValueError("Token de dispositivo no valido")
        return valor


class Generacion(Entrada):
    solicitud: UUID


def crear_app(servicio=None, push=None, catalogo=None, novedades=None, real=None, acceso_real=None, gestor=None, historial=None):
    if servicio is None:
        if os.environ.get("TINOTIFY_MODE") != "demo":
            raise RuntimeError("La aplicacion demo requiere TINOTIFY_MODE=demo")
        servicio = ServicioDemo([os.environ.get("TINOTIFY_DEMO_CODE_A", ""), os.environ.get("TINOTIFY_DEMO_CODE_B", "")])
    push = push or ExpoPush(os.environ.get("TINOTIFY_EXPO_ACCESS_TOKEN"))
    catalogo = catalogo if catalogo is not None else CatalogoSintetico()
    if novedades is None and os.environ.get("TINOTIFY_LOCAL_DB"):
        novedades = ServicioNovedadesLocal(AlmacenSqliteLocal(os.environ["TINOTIFY_LOCAL_DB"]))
    # Datos reales: archivo y código de acceso propios y distintos del catálogo y de la base sintética.
    ruta_real, codigo_real = os.environ.get("TINOTIFY_REAL_DB"), os.environ.get("TINOTIFY_REAL_ACCESS_CODE")
    if real is None and (ruta_real or codigo_real):
        if not (ruta_real and codigo_real):
            raise RuntimeError("La consulta local real requiere TINOTIFY_REAL_DB y TINOTIFY_REAL_ACCESS_CODE")
        real = ServicioNovedadesLocal(AlmacenSqliteLocal(ruta_real, perfil="real"), instancia=INSTANCIA_REAL)
        acceso_real = AccesoLocal(codigo_real)
    if real is not None and acceso_real is None:
        raise RuntimeError("Los datos reales exigen un codigo de acceso local")
    # Sesión SIGAC temporal desde Android: apagada por defecto; exige explícitamente los datos reales protegidos.
    if gestor is None and os.environ.get("TINOTIFY_REAL_SESSION") == "1":
        if real is None:
            raise RuntimeError("La sesion SIGAC local requiere TINOTIFY_REAL_DB y TINOTIFY_REAL_ACCESS_CODE")
        from tinotify.services.sesion_sigac_local import GestorSesionSigac  # carga perezosa: nunca en producción
        gestor = GestorSesionSigac(real)
    if historial is not None and real is None:
        raise RuntimeError("El historial temporal requiere los datos reales protegidos")
    if gestor is not None and real is None:
        raise RuntimeError("La sesion SIGAC local requiere los datos reales protegidos")

    @asynccontextmanager
    async def lifespan(_):
        yield
        if gestor is not None:  # nunca queda un monitor vivo tras apagar o reiniciar el servidor
            await run_in_threadpool(gestor.apagar)
        await push.cerrar()

    app = FastAPI(title="Tinotify Demo", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def sesion(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credencial is None:
            raise HTTPException(401, "Acceso demo requerido")
        servicio.listar(credencial.credentials)
        return credencial.credentials

    Usuario = Annotated[str, Depends(sesion)]

    @app.exception_handler(RequestValidationError)
    async def entrada_invalida(_, __):
        return JSONResponse({"detail": "Entrada demo no valida"}, status_code=422)

    @app.exception_handler(AccesoDemo)
    async def acceso_invalido(_, __):
        return JSONResponse({"detail": "Sesion demo no valida o caducada"}, status_code=401)

    @app.exception_handler(KeyError)
    async def no_encontrado(_, __):
        return JSONResponse({"detail": "Proceso no disponible"}, status_code=404)

    @app.exception_handler(ConflictoDemo)
    async def conflicto(_, __):
        return JSONResponse({"detail": "Limite o vinculacion demo incompatible"}, status_code=409)

    @app.exception_handler(ConnectionError)
    async def origen_fallido(_, __):
        return JSONResponse({"detail": "Origen simulado no disponible; estado anterior conservado"}, status_code=503)

    async def enviar(usuario):
        for destino, evento in servicio.tomar_envios(usuario):
            estado, ticket = await push.enviar(destino, evento)
            servicio.resolver_envio(usuario, evento, estado, ticket)

    @app.exception_handler(DemasiadosIntentos)
    async def demasiados_intentos(_, __):
        return JSONResponse({"detail": "Demasiados intentos; espera un minuto"}, status_code=429)

    if real is not None:
        registrar_rutas_reales(app, real, acceso_real, gestor, historial)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Solo lectura y sin credenciales: datos sintéticos y públicos de la app local; no tocan SIGAC.
    @app.get("/demo/catalog/cases")
    async def casos_sinteticos():
        return catalogo.listar()

    @app.get("/demo/catalog/cases/{caso}/actuaciones")
    async def actuaciones_sinteticas(caso: UUID):
        return catalogo.actuaciones(str(caso))

    # Novedades persistidas localmente: solo lectura. No hay rutas que escriban, observen o marquen avisos
    # como procesados; consultar un aviso nunca lo da por entregado.
    def locales():
        if novedades is None:
            raise HTTPException(503, "Persistencia local no configurada")
        return novedades

    @app.get("/demo/local/cases")
    async def casos_locales():
        return locales().listar_casos()

    @app.get("/demo/local/cases/{caso}")
    async def detalle_local(caso: UUID):
        return locales().detalle(str(caso))

    @app.get("/demo/local/novedades")
    async def novedades_locales():
        return locales().novedades()

    @app.exception_handler(AlmacenLocalNoDisponible)
    async def almacen_no_disponible(_, __):
        return JSONResponse({"detail": "Almacen local no disponible; estado anterior conservado"}, status_code=503)

    @app.post("/demo/sessions")
    async def ingresar(datos: Acceso):
        return {"token": servicio.ingresar(datos.codigo.get_secret_value()), "demo": True, "expires_in": 3600}

    @app.delete("/demo/session", status_code=204)
    async def salir(usuario: Usuario):
        servicio.salir(usuario)

    @app.get("/demo/cases")
    async def casos(usuario: Usuario):
        return servicio.listar(usuario)

    @app.get("/demo/cases/{caso}")
    async def detalle(caso: UUID, usuario: Usuario):
        return servicio.detalle(usuario, str(caso))

    @app.post("/demo/cases/{caso}/sync")
    async def sincronizar(caso: UUID, usuario: Usuario):
        servicio.sincronizar(usuario, str(caso))
        await enviar(usuario)
        return servicio.detalle(usuario, str(caso))

    @app.post("/demo/cases/{caso}/actuaciones")
    async def generar(caso: UUID, datos: Generacion, usuario: Usuario):
        servicio.agregar(usuario, str(caso), str(datos.solicitud))
        await enviar(usuario)
        return servicio.detalle(usuario, str(caso))

    @app.post("/demo/device", status_code=204)
    async def dispositivo(datos: Dispositivo, usuario: Usuario):
        servicio.registrar(usuario, datos.token.get_secret_value())

    @app.post("/demo/push/receipts")
    async def recibos(usuario: Usuario):
        servicio.aplicar_recibos(usuario, await push.recibos(servicio.tickets(usuario)))
        return {"status": "consultado"}

    return app
