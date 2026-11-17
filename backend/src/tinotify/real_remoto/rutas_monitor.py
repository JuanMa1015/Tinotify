"""Rutas del monitor. Dos credenciales distintas: el token de la app (credenciales y estado) y el token del monitor (GitHub Actions).

Ninguna respuesta lleva identificadores de expedientes, textos judiciales ni credenciales: solo conteos, estados y los UUID de los
avisos pendientes (la bandeja que Actions consulta para enviar el correo y confirmar la entrega).
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.real_remoto.almacen import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.real_remoto.cifrado import CifradoNoValido
from tinotify.real_remoto.comun import Acceso
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, SesionOcupada
from tinotify.real_remoto.servicio_monitor import SinCredenciales

registro = logging.getLogger("tinotify.real_remoto")


def registrar_monitor(app: FastAPI, *, servicio, config, protegidas_app, http_desde_sigac, reloj):
    acceso_monitor = Acceso(config.monitor.token_monitor, reloj=reloj)
    bearer = HTTPBearer(auto_error=False)

    def autorizar_monitor(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        resultado = acceso_monitor.comprobar(credencial.credentials if credencial else None)
        if resultado is True:
            return
        if resultado is None:
            raise HTTPException(429, "Demasiados intentos")
        raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})

    protegidas_monitor = [Depends(autorizar_monitor)]

    def almacen_no_disponible():
        registro.warning("almacen_no_disponible")
        return HTTPException(503, "Almacen no disponible", headers={"Retry-After": "30"})

    @app.get("/real/monitor/estado", dependencies=protegidas_app)
    async def estado_monitor():
        try:
            return await run_in_threadpool(servicio.estado)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.delete("/real/credenciales", dependencies=protegidas_app)
    async def olvidar_credenciales():
        try:
            await run_in_threadpool(servicio.olvidar_credenciales)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"credenciales_guardadas": False}

    @app.post("/real/monitor/ejecutar", dependencies=protegidas_monitor)
    async def ejecutar():
        try:
            return await run_in_threadpool(servicio.ejecutar)
        except SinCredenciales:
            raise HTTPException(412, "No hay credenciales guardadas") from None
        except CifradoNoValido:
            registro.error("cifrado_no_valido")  # llave distinta o datos alterados; nunca detalles
            raise HTTPException(503, "Servicio no configurado") from None
        except SesionOcupada:
            raise HTTPException(409, "Ya hay un acceso en curso") from None
        except DemasiadosIntentosLogin as error:
            raise HTTPException(429, "Demasiados intentos de acceso; espera", headers={"Retry-After": str(error.espera_s)}) from None
        except SigacClientError as error:
            raise http_desde_sigac(error) from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    class Dispositivo(BaseModel):
        model_config = ConfigDict(extra="forbid")
        token: Annotated[str, StringConstraints(min_length=20, max_length=4096, pattern=r"^\S+$")]

    @app.post("/real/dispositivos", dependencies=protegidas_app)
    async def registrar_dispositivo(datos: Dispositivo):
        try:
            await run_in_threadpool(servicio.registrar_dispositivo, datos.token)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"registrado": True}

    @app.delete("/real/dispositivos", dependencies=protegidas_app)
    async def borrar_dispositivo(datos: Dispositivo):
        try:
            borrado = await run_in_threadpool(servicio.borrar_dispositivo, datos.token)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"borrado": borrado}

    @app.get("/real/monitor/avisos", dependencies=protegidas_monitor)
    async def avisos():
        try:
            return {"avisos": await run_in_threadpool(servicio.avisos_pendientes)}
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.post("/real/monitor/avisos/{aviso}/entregado", dependencies=protegidas_monitor)
    async def entregado(aviso: UUID):
        try:
            ok = await run_in_threadpool(servicio.marcar_entregado, str(aviso))
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        if not ok:
            raise HTTPException(404, "Aviso no pendiente")
        return {"entregado": True}
