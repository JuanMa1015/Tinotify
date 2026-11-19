"""Rutas de cuentas (`/auth/*`) y administración (`/admin/*`): registro por invitación, acceso con código por correo, sesión por dispositivo,
borrado de cuenta y panel de administración. No hay contraseñas de Tinotify.

Los errores llevan códigos de catálogo y nunca el correo, el código ni el token recibidos.
"""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.almacen import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.real_remoto.servicio_cuentas import (
    AccionNoPermitida, CodigoNoValido, ConfirmacionIncorrecta, RegistroNoValido, UsuarioNoEncontrado)

registro = logging.getLogger("tinotify.real_remoto")
CONSENTIMIENTO_VIGENTE = "consentimiento-v1"
ID_USUARIO = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
MAX_INTENTOS, VENTANA_S = 30, 900  # tope GLOBAL de registros y entradas por ventana (el proxy de Render oculta la IP real)

Correo = Annotated[str, StringConstraints(min_length=3, max_length=254)]
Codigo = Annotated[str, StringConstraints(min_length=4, max_length=20)]
Invitacion = Annotated[str, StringConstraints(min_length=4, max_length=40)]
Dispositivo = Annotated[str, StringConstraints(max_length=60)] | None


class Limitador:
    def __init__(self, maximo, ventana_s, reloj):
        self._maximo, self._ventana, self._reloj, self._marcas = maximo, ventana_s, reloj, []

    def permitir(self):
        ahora = self._reloj()
        self._marcas = [t for t in self._marcas if ahora - t < self._ventana]
        if len(self._marcas) >= self._maximo:
            return False
        self._marcas.append(ahora)
        return True


class PedirRegistro(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo
    invitacion: Invitacion


class Registro(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo
    codigo: Codigo
    invitacion: Invitacion
    consentimiento: Annotated[str, StringConstraints(max_length=40)]
    dispositivo: Dispositivo = None


class PedirAcceso(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo


class Entrar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo
    codigo: Codigo
    dispositivo: Dispositivo = None


class BorradoCuenta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo


class Activo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activo: bool


class RolAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin: bool


def registrar_cuentas(app: FastAPI, *, servicio, protegidas_app, reloj, admin_actual=None):
    limitador = Limitador(MAX_INTENTOS, VENTANA_S, reloj)
    limitador_correos = Limitador(10, VENTANA_S, reloj)  # tope GLOBAL de correos con código (cuota diaria del proveedor)
    bearer = HTTPBearer(auto_error=False)

    def sesion(credencial: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        token = credencial.credentials if credencial else None
        usuario = servicio.autenticar(token)
        if usuario is None:
            raise HTTPException(401, "Acceso requerido", headers={"WWW-Authenticate": "Bearer"})
        return usuario, token

    def sin_almacen():
        registro.warning("almacen_no_disponible")
        return HTTPException(503, "Almacen no disponible", headers={"Retry-After": "30"})

    def limitar(correos=False):
        if not limitador.permitir() or (correos and not limitador_correos.permitir()):
            raise HTTPException(429, "Demasiados intentos; espera unos minutos", headers={"Retry-After": "300"})

    @app.post("/auth/registro/codigo")
    async def pedir_codigo_registro(datos: PedirRegistro):
        """Paso 1 de la cuenta nueva: manda el código al correo. Estados: `enviado`, `invitacion_invalida`, `ya_registrado`, `correo_invalido`, `fallo_envio`."""
        limitar(correos=True)
        try:
            estado = await run_in_threadpool(servicio.solicitar_codigo_registro, datos.correo, datos.invitacion)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"estado": estado}

    @app.post("/auth/registro")
    async def registrar(datos: Registro):
        """Paso 2: con el código del correo crea la cuenta y abre la sesión."""
        limitar()
        if datos.consentimiento != CONSENTIMIENTO_VIGENTE:
            raise HTTPException(422, "consentimiento_no_valido")
        try:
            token, usuario = await run_in_threadpool(servicio.registrar, datos.correo, datos.codigo, datos.invitacion,
                                                     datos.consentimiento, datos.dispositivo)
        except c.DatosNoValidos as error:
            raise HTTPException(422, f"datos_no_validos:{error}") from None
        except RegistroNoValido:
            raise HTTPException(400, "No se pudo crear la cuenta. Revisa el código y la invitación.") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"token": token, "usuario": usuario.id}

    @app.post("/auth/entrar/codigo")
    async def pedir_codigo_acceso(datos: PedirAcceso):
        """Manda un código de un solo uso para entrar. Estados: `enviado`, `no_registrado`, `limite`, `fallo_envio`."""
        limitar(correos=True)
        try:
            estado = await run_in_threadpool(servicio.solicitar_codigo_acceso, datos.correo)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"estado": estado}

    @app.post("/auth/entrar")
    async def entrar(datos: Entrar):
        limitar()
        try:
            token, usuario = await run_in_threadpool(servicio.entrar, datos.correo, datos.codigo, datos.dispositivo)
        except CodigoNoValido:
            raise HTTPException(400, "El código no es válido o ya venció") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"token": token, "usuario": usuario.id}

    @app.get("/auth/yo")
    async def yo(actual: Annotated[tuple, Depends(sesion)]):
        return {"usuario": actual[0].id, "admin": actual[0].es_admin}

    @app.post("/auth/logout")
    async def salir(actual: Annotated[tuple, Depends(sesion)]):
        try:
            await run_in_threadpool(servicio.cerrar_sesion, actual[1])
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"cerrada": True}

    @app.delete("/auth/cuenta")
    async def borrar(datos: BorradoCuenta, actual: Annotated[tuple, Depends(sesion)]):
        limitar()
        try:
            await run_in_threadpool(servicio.eliminar_cuenta, actual[0].id, datos.correo)
        except ConfirmacionIncorrecta:
            raise HTTPException(400, "El correo no coincide con el de la cuenta") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"borrada": True}

    admin = [Depends(admin_actual)] if admin_actual is not None else protegidas_app

    @app.post("/auth/invitaciones", dependencies=admin)
    async def invitar():
        """Solo el propietario (código del servidor) o una persona administradora crea invitaciones. El código se muestra una vez y solo se guarda su hash."""
        try:
            codigo = await run_in_threadpool(servicio.crear_invitacion)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"codigo": codigo, "vigencia_dias": 7}

    @app.post("/auth/correo/prueba", dependencies=protegidas_app)
    async def probar_correo():
        """Solo el propietario: envía un correo de prueba al remitente de Brevo y dice el motivo si falla (código de Brevo, sin datos)."""
        enviado, motivo = await run_in_threadpool(servicio.probar_correo)
        return {"enviado": enviado, "motivo": motivo}

    if admin_actual is None:
        return

    def _traducir(accion, *args):
        try:
            accion(*args)
        except UsuarioNoEncontrado:
            raise HTTPException(404, "Usuario no encontrado") from None
        except AccionNoPermitida:
            raise HTTPException(409, "No puedes hacer eso con tu propia cuenta") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None

    @app.get("/admin/usuarios")
    async def admin_usuarios(quien: Annotated[str | None, Depends(admin_actual)]):
        """Panel de administración: cuentas con su estado y conteos. Nunca credenciales de SIGAC ni expedientes."""
        try:
            return {"usuarios": await run_in_threadpool(servicio.listar_usuarios), "yo": quien}
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None

    @app.post("/admin/usuarios/{objetivo}/activo")
    async def admin_activo(objetivo: Annotated[str, Path(pattern=ID_USUARIO)], datos: Activo, quien: Annotated[str | None, Depends(admin_actual)]):
        await run_in_threadpool(_traducir, servicio.fijar_activo, objetivo, datos.activo, quien)
        return {"activo": datos.activo}

    @app.post("/admin/usuarios/{objetivo}/admin")
    async def admin_rol(objetivo: Annotated[str, Path(pattern=ID_USUARIO)], datos: RolAdmin, quien: Annotated[str | None, Depends(admin_actual)]):
        await run_in_threadpool(_traducir, servicio.fijar_admin, objetivo, datos.admin, quien)
        return {"admin": datos.admin}

    @app.delete("/admin/usuarios/{objetivo}/datos")
    async def admin_borrar_datos(objetivo: Annotated[str, Path(pattern=ID_USUARIO)], quien: Annotated[str | None, Depends(admin_actual)]):
        await run_in_threadpool(_traducir, servicio.borrar_datos, objetivo, quien)
        return {"borrados": True}

    @app.delete("/admin/usuarios/{objetivo}")
    async def admin_eliminar(objetivo: Annotated[str, Path(pattern=ID_USUARIO)], quien: Annotated[str | None, Depends(admin_actual)]):
        await run_in_threadpool(_traducir, servicio.eliminar_usuario, objetivo, quien)
        return {"eliminada": True}
