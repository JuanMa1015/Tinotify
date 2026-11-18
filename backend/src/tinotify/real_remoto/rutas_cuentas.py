"""Rutas de cuentas (`/auth/*`): registro por invitación, login, sesión por dispositivo, cambio de clave y borrado de cuenta.

Fase 1 del multiusuario: estas rutas NO dan acceso a los datos del monitor. Las rutas `/real/*` siguen aceptando solo el token del
propietario hasta que los datos se separen por usuario (fase 2); un token de usuario nunca abre datos ajenos.
Los errores llevan códigos de catálogo y nunca el correo, la clave, la invitación ni el token recibidos.
"""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.almacen import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.real_remoto.servicio_cuentas import CredencialesIncorrectas, CuentaBloqueada, RegistroNoValido

registro = logging.getLogger("tinotify.real_remoto")
CONSENTIMIENTO_VIGENTE = "consentimiento-v1"
MAX_INTENTOS, VENTANA_S = 30, 900  # tope GLOBAL de registros e inicios de sesión por ventana (el proxy de Render oculta la IP real)

Correo = Annotated[str, StringConstraints(min_length=3, max_length=254)]
Clave = Annotated[str, StringConstraints(min_length=1, max_length=128)]
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


class Registro(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo
    clave: Clave
    invitacion: Annotated[str, StringConstraints(min_length=4, max_length=40)]
    consentimiento: Annotated[str, StringConstraints(max_length=40)]
    dispositivo: Dispositivo = None


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: Correo
    clave: Clave
    dispositivo: Dispositivo = None


class CambioClave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual: Clave
    nueva: Clave


class BorradoCuenta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clave: Clave


def registrar_cuentas(app: FastAPI, *, servicio, protegidas_app, reloj):
    limitador = Limitador(MAX_INTENTOS, VENTANA_S, reloj)
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

    def limitar():
        if not limitador.permitir():
            raise HTTPException(429, "Demasiados intentos; espera unos minutos", headers={"Retry-After": "300"})

    @app.post("/auth/registro")
    async def registrar(datos: Registro):
        limitar()
        if datos.consentimiento != CONSENTIMIENTO_VIGENTE:
            raise HTTPException(422, "consentimiento_no_valido")
        try:
            token, usuario = await run_in_threadpool(servicio.registrar, datos.correo, datos.clave, datos.invitacion,
                                                     datos.consentimiento, datos.dispositivo)
        except c.DatosNoValidos as error:
            raise HTTPException(422, f"datos_no_validos:{error}") from None
        except RegistroNoValido:
            raise HTTPException(400, "No se pudo crear la cuenta. Revisa la invitación.") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"token": token, "usuario": usuario.id}

    @app.post("/auth/login")
    async def iniciar(datos: Login):
        limitar()
        try:
            token, usuario = await run_in_threadpool(servicio.iniciar_sesion, datos.correo, datos.clave, datos.dispositivo)
        except CredencialesIncorrectas:
            raise HTTPException(401, "Correo o contraseña incorrectos") from None
        except CuentaBloqueada as error:
            raise HTTPException(429, "Cuenta bloqueada temporalmente", headers={"Retry-After": str(error.espera_s)}) from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"token": token, "usuario": usuario.id}

    @app.get("/auth/yo")
    async def yo(actual: Annotated[tuple, Depends(sesion)]):
        return {"usuario": actual[0].id}

    @app.post("/auth/logout")
    async def salir(actual: Annotated[tuple, Depends(sesion)]):
        try:
            await run_in_threadpool(servicio.cerrar_sesion, actual[1])
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"cerrada": True}

    @app.post("/auth/cambiar-clave")
    async def cambiar(datos: CambioClave, actual: Annotated[tuple, Depends(sesion)]):
        limitar()
        try:
            await run_in_threadpool(servicio.cambiar_clave, actual[0].id, datos.actual, datos.nueva, actual[1])
        except c.DatosNoValidos as error:
            raise HTTPException(422, f"datos_no_validos:{error}") from None
        except CredencialesIncorrectas:
            raise HTTPException(401, "La contraseña actual no es correcta") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"cambiada": True}

    @app.delete("/auth/cuenta")
    async def borrar(datos: BorradoCuenta, actual: Annotated[tuple, Depends(sesion)]):
        limitar()
        try:
            await run_in_threadpool(servicio.eliminar_cuenta, actual[0].id, datos.clave)
        except CredencialesIncorrectas:
            raise HTTPException(401, "La contraseña no es correcta") from None
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"borrada": True}

    @app.post("/auth/invitaciones", dependencies=protegidas_app)
    async def invitar():
        """Solo el propietario (token de la app) crea invitaciones. El código se muestra una vez y solo se guarda su hash."""
        try:
            codigo = await run_in_threadpool(servicio.crear_invitacion)
        except (AlmacenNoDisponible, AlmacenIncompatible):
            raise sin_almacen() from None
        return {"codigo": codigo, "vigencia_dias": 7}
