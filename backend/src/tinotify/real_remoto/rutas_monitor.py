"""Rutas del monitor. Dos credenciales distintas: el token de la app (credenciales y estado) y el token del monitor (GitHub Actions).

Ninguna respuesta lleva identificadores de expedientes, textos judiciales ni credenciales: solo conteos, estados y los UUID de los
avisos pendientes (la bandeja que Actions consulta para enviar el correo y confirmar la entrega).
"""

from contextlib import contextmanager
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints
from starlette.concurrency import run_in_threadpool

from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.real_remoto.almacen import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.real_remoto.cifrado import CifradoNoValido
from tinotify.real_remoto.comun import Acceso
from tinotify.real_remoto.sesiones import DemasiadosIntentosLogin, SesionOcupada
from tinotify.real_remoto.servicio_monitor import AnexoNoDisponible, ExpedienteNoEncontrado, SinCredenciales

registro = logging.getLogger("tinotify.real_remoto")


def registrar_monitor(app: FastAPI, *, servicios, servicio_actual, config, protegidas_app, http_desde_sigac, reloj):
    servicio = servicios.para(None)  # propietario: lo usan las rutas del monitor (token de Actions)
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

    @contextmanager
    def traduciendo():
        """Errores del dominio -> respuestas HTTP: las mismas en todas las rutas que leen o escriben SIGAC y la base."""
        try:
            yield
        except ExpedienteNoEncontrado:
            raise HTTPException(404, "Expediente no encontrado") from None
        except AnexoNoDisponible:
            raise HTTPException(404, "Anexo no disponible; abre el expediente de nuevo") from None
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

    @app.get("/real/monitor/estado")
    async def estado_monitor(servicio: Annotated[object, Depends(servicio_actual)]):
        try:
            return await run_in_threadpool(servicio.estado)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.get("/real/monitor/ejecuciones")
    async def ejecuciones(servicio: Annotated[object, Depends(servicio_actual)], limite: Annotated[int, Query(ge=1, le=100)] = 30):
        try:
            return {"ejecuciones": await run_in_threadpool(servicio.ejecuciones, limite)}
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.get("/real/expedientes")
    async def expedientes(servicio: Annotated[object, Depends(servicio_actual)]):
        try:
            return {"expedientes": await run_in_threadpool(servicio.expedientes)}
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.get("/real/expedientes/{caso}/actuaciones")
    async def actuaciones_expediente(servicio: Annotated[object, Depends(servicio_actual)], caso: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]):
        with traduciendo():
            return {"actuaciones": await run_in_threadpool(servicio.historial_expediente, caso)}

    @app.get("/real/expedientes/{caso}/actuaciones/{actuacion}/anexos/{anexo}")
    async def descargar_anexo(servicio: Annotated[object, Depends(servicio_actual)], caso: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
                              actuacion: Annotated[int, Path(ge=0, le=100000)], anexo: Annotated[int, Path(ge=0, le=1000)]):
        """Entrega el archivo de un anexo, descargado de SIGAC en este momento con las credenciales guardadas. No se almacena."""
        with traduciendo():
            contenido, tipo, nombre = await run_in_threadpool(servicio.descargar_anexo, caso, actuacion, anexo)
        seguro = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in nombre)[:120] or "anexo"
        return Response(contenido, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{seguro}"'})

    class Vistos(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None

    @app.post("/real/expedientes/vistos")
    async def marcar_vistos(servicio: Annotated[object, Depends(servicio_actual)], datos: Vistos):
        try:
            return {"actualizados": await run_in_threadpool(servicio.marcar_vistos, datos.id)}
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.post("/real/dispositivos/prueba")
    async def prueba_push(servicio: Annotated[object, Depends(servicio_actual)]):
        try:
            r = await run_in_threadpool(servicio.enviar_prueba)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        if r is None:
            raise HTTPException(412, "Las notificaciones no están configuradas en el servidor")
        return {"enviados": r[0], "invalidos": r[1]}

    @app.delete("/real/credenciales")
    async def olvidar_credenciales(servicio: Annotated[object, Depends(servicio_actual)]):
        try:
            await run_in_threadpool(servicio.olvidar_credenciales)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"credenciales_guardadas": False}

    @app.get("/real/monitor/usuarios", dependencies=protegidas_monitor)
    async def usuarios():
        try:
            return await run_in_threadpool(servicios.usuarios)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None

    @app.post("/real/monitor/ejecutar", dependencies=protegidas_monitor)
    async def ejecutar(usuario: Annotated[str, Query(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")] | None = None):
        with traduciendo():
            return await run_in_threadpool(servicios.para(usuario).ejecutar)

    class Conexion(BaseModel):
        model_config = ConfigDict(extra="forbid")
        usuario: Annotated[SecretStr, StringConstraints(min_length=1, max_length=200)]
        clave: Annotated[SecretStr, StringConstraints(min_length=1, max_length=200)]
        caso_login: Annotated[SecretStr, StringConstraints(max_length=100)] | None = None

    @app.post("/real/conectar")
    async def conectar(servicio: Annotated[object, Depends(servicio_actual)], datos: Conexion):
        """Guarda las credenciales de SIGAC de este usuario (cifradas) tras comprobar que SIGAC las acepta. La clave nunca se devuelve."""
        with traduciendo():
            n = await run_in_threadpool(servicio.conectar, datos.usuario.get_secret_value(), datos.clave.get_secret_value(),
                                        datos.caso_login.get_secret_value() if datos.caso_login else None)
        return {"conectado": True, "expedientes": n}

    class Dispositivo(BaseModel):
        model_config = ConfigDict(extra="forbid")
        token: Annotated[str, StringConstraints(min_length=20, max_length=4096, pattern=r"^\S+$")]

    @app.post("/real/dispositivos")
    async def registrar_dispositivo(servicio: Annotated[object, Depends(servicio_actual)], datos: Dispositivo):
        try:
            await run_in_threadpool(servicio.registrar_dispositivo, datos.token)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"registrado": True}

    @app.delete("/real/dispositivos")
    async def borrar_dispositivo(servicio: Annotated[object, Depends(servicio_actual)], datos: Dispositivo):
        try:
            borrado = await run_in_threadpool(servicio.borrar_dispositivo, datos.token)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        return {"borrado": borrado}

    class Canal(BaseModel):
        model_config = ConfigDict(extra="forbid")
        canal: Literal["correo"]
        estado: Literal["enviado", "fallido", "desactivado"]

    @app.post("/real/monitor/avisos/{aviso}/canal", dependencies=protegidas_monitor)
    async def canal_aviso(aviso: UUID, datos: Canal):
        try:
            ok = await run_in_threadpool(servicio.canal_aviso, str(aviso), datos.canal, datos.estado)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise almacen_no_disponible() from None
        if not ok:
            raise HTTPException(404, "Aviso no encontrado")
        return {"registrado": True}

    @app.get("/real/monitor/avisos", dependencies=protegidas_monitor)
    async def avisos():
        try:
            return {"avisos": await run_in_threadpool(servicios.avisos_pendientes_todos)}
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
