"""Configuración del backend remoto real. Todo se valida al arrancar y falla cerrado.

Los errores llevan un código estable, nunca valores. Las credenciales SIGAC jamás se configuran aquí: o existen en memoria
durante un login o, si la persona usuaria lo pide, se guardan CIFRADAS en la base (la llave está solo en este entorno).
El monitor (base de datos, llave de cifrado y token propio) es opcional: se activa solo si están TODAS sus variables.
"""

import base64
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from tinotify.real_remoto.comun import (
    MODO_LOCAL, MODO_REMOTO, PROXIES_PRIVADAS, TLS_DIRECTO, TLS_PROXY, ConfiguracionInsegura, _numero, _proxies,
    _rechazar, validar_token,
)

PREFIJO = "TINOTIFY_RR_"
VARIABLES_MONITOR = {PREFIJO + x for x in (
    "PG_HOST", "PG_PORT", "PG_DBNAME", "PG_USER", "PG_PASSWORD", "PG_CA_FILE", "CLAVE_CIFRADO", "MONITOR_TOKEN")}
OBLIGATORIAS_MONITOR = {PREFIJO + x for x in ("PG_HOST", "PG_USER", "PG_PASSWORD", "PG_CA_FILE", "CLAVE_CIFRADO", "MONITOR_TOKEN")}
VARIABLES = {PREFIJO + x for x in (
    "MODO", "TOKEN", "TLS", "PROXIES_CONFIABLES", "ACREDITACION_FILE", "REFERENCIA_FILE", "TIPO", "TOTAL_CASOS",
    "TTL_MIN", "MAX_LOGINS", "VENTANA_LOGIN_MIN", "FCM_CUENTA_SERVICIO", "CUENTAS", "BREVO_CLAVE", "BREVO_REMITENTE")} | VARIABLES_MONITOR
_HOST_PG = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USUARIO_PG = re.compile(r"^tinotify_real_login(\.[a-z0-9]{8,40})?$")


@dataclass(frozen=True)
class ConfigPg:
    """Conexión a PostgreSQL por componentes (nunca un DSN): TLS verify-full con CA explícita, salvo `tls=False`, que solo
    pueden construir las pruebas en código (no existe variable de entorno que lo permita)."""

    host: str
    puerto: int
    base: str
    usuario: str
    password: str = field(repr=False)
    ca: Path | None = None
    tls: bool = True
    espera_s: float = 8.0

    def __repr__(self):
        return f"ConfigPg(host=<oculto>, usuario=<oculto>, tls={self.tls})"


@dataclass(frozen=True)
class ConfigMonitor:
    pg: ConfigPg
    clave_cifrado: bytes = field(repr=False)
    token_monitor: str = field(repr=False)

    def __repr__(self):
        return "ConfigMonitor(<oculto>)"


def _monitor(e, token):
    presentes = {k for k in VARIABLES_MONITOR if e.get(k) not in (None, "")}
    if not presentes:
        return None
    if not OBLIGATORIAS_MONITOR <= presentes:
        _rechazar("monitor_incompleto")
    host = e[PREFIJO + "PG_HOST"]
    if not _HOST_PG.fullmatch(host) or host.startswith("-"):
        _rechazar("pg_host_no_valido")
    puerto = _numero(e.get(PREFIJO + "PG_PORT", "5432"), 1, 65535, "pg_puerto_no_valido", tipo=int)
    if puerto == 6543:
        _rechazar("pg_pooler_transaccional_no_admitido")
    base = e.get(PREFIJO + "PG_DBNAME", "postgres")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,63}", base):
        _rechazar("pg_base_no_valida")
    usuario = e[PREFIJO + "PG_USER"]
    if not _USUARIO_PG.fullmatch(usuario):
        _rechazar("pg_usuario_no_restringido")  # solo tinotify_real_login[.<ref>]; nunca postgres ni service_role
    password = e[PREFIJO + "PG_PASSWORD"]
    if len(password) < 16 or len(password) > 256 or re.search(r"[\x00-\x1f\x7f]", password) or password != password.strip():
        _rechazar("pg_password_ausente_o_insegura")
    ca = _archivo(e[PREFIJO + "PG_CA_FILE"], "pg_ca_ausente_o_invalida", maximo=1_000_000)
    try:
        if b"BEGIN CERTIFICATE" not in ca.read_bytes():
            _rechazar("pg_ca_ausente_o_invalida")
    except OSError:
        _rechazar("pg_ca_ausente_o_invalida")
    clave = clave_desde_texto(e[PREFIJO + "CLAVE_CIFRADO"])
    token_monitor = validar_token(e[PREFIJO + "MONITOR_TOKEN"])
    if token_monitor == token:
        _rechazar("token_monitor_igual_al_de_la_app")
    return ConfigMonitor(ConfigPg(host, puerto, base, usuario, password, ca), clave, token_monitor)


def clave_desde_texto(texto):
    """Llave AES-256 en base64 (estándar o URL-safe, con o sin relleno): exactamente 32 bytes."""
    try:
        crudo = base64.urlsafe_b64decode(texto.strip().replace("+", "-").replace("/", "_") + "=" * (-len(texto.strip()) % 4))
    except (ValueError, TypeError, AttributeError):
        _rechazar("clave_cifrado_invalida")
    if len(crudo) != 32 or len(set(crudo)) < 8:
        _rechazar("clave_cifrado_invalida")
    return crudo
# Nada de otros entornos ni de credenciales ajenas: ni sintético, ni real local, ni SIGAC, ni bases de datos.
PROHIBIDOS_PREFIJO = ("TINOTIFY_SR_", "TINOTIFY_REAL_", "TINOTIFY_SIGAC_", "SIGAC_", "SUPABASE", "PG")
PROHIBIDOS_NOMBRE = ("DATABASE_URL", "TINOTIFY_LOCAL_DB", "TINOTIFY_DEMO_CODE_A", "TINOTIFY_DEMO_CODE_B")


class VariablesAjenas(ConfiguracionInsegura):
    """Variables que no pertenecen a este servicio. Se informan SOLO los nombres (nunca los valores), para poder
    retirarlas del servicio sin adivinar."""

    def __init__(self, codigo, nombres):
        super().__init__(codigo)
        self.nombres = tuple(sorted(nombres))
        self.args = (f"Configuracion rechazada: {codigo}: {', '.join(self.nombres)}",)


def _archivo(ruta, codigo, *, maximo=3_000_000):
    if not isinstance(ruta, str) or not ruta.strip() or "\x00" in ruta:
        _rechazar(codigo)
    try:
        r = Path(ruta).resolve()
        if not r.is_file() or r.stat().st_size > maximo:
            _rechazar(codigo)
    except (OSError, ValueError, RuntimeError):
        _rechazar(codigo)
    return r


@dataclass(frozen=True)
class Config:
    modo: str
    token: str = field(repr=False)
    acreditacion: Path = field(repr=False, default=None)
    referencia: Path = field(repr=False, default=None)
    tls: str | None = None
    proxies_confiables: tuple = ()
    tipo: str = "2"
    total_casos: int | None = None   # opcional: si no se fija, el listado se verifica estructuralmente
    ttl_s: int = 1200
    max_logins: int = 3
    ventana_login_s: int = 900
    monitor: ConfigMonitor | None = None   # opcional: base de datos, llave de cifrado y token propios
    cuentas: bool = False   # opcional: rutas /auth (registro por invitación). Exige el monitor y la migración de cuentas aplicada
    correo_api: tuple | None = field(repr=False, default=None)   # opcional: (clave de Brevo, remitente) para el código de recuperación; exige cuentas
    fcm_cuenta: Path | None = field(repr=False, default=None)   # opcional: cuenta de servicio de Firebase (push); exige el monitor

    def __repr__(self):
        return f"Config(modo={self.modo!r}, tls={self.tls!r})"

    @property
    def remoto(self):
        return self.modo == MODO_REMOTO

    @classmethod
    def desde_entorno(cls, e=None):
        e = os.environ if e is None else e
        ajenas = [str(k).upper() for k in e
                  if str(k).upper().startswith(PROHIBIDOS_PREFIJO) or str(k).upper() in PROHIBIDOS_NOMBRE]
        if ajenas:
            raise VariablesAjenas("variable_ajena_presente", ajenas)
        desconocidas = [str(k).upper() for k in e if str(k).upper().startswith(PREFIJO) and str(k).upper() not in VARIABLES]
        if desconocidas:
            raise VariablesAjenas("opcion_desconocida", desconocidas)
        modo = e.get(PREFIJO + "MODO", "")
        if modo not in (MODO_LOCAL, MODO_REMOTO):
            _rechazar("modo_no_valido")
        token = validar_token(e.get(PREFIJO + "TOKEN", ""))
        tls, proxies = None, ()
        if modo == MODO_REMOTO:
            tls = e.get(PREFIJO + "TLS", "")
            if tls not in (TLS_DIRECTO, TLS_PROXY):
                _rechazar("tls_no_valido")
            if tls == TLS_PROXY:
                proxies = _proxies(e.get(PREFIJO + "PROXIES_CONFIABLES", ""))
        tipo = e.get(PREFIJO + "TIPO", "2")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", tipo):
            _rechazar("tipo_no_valido")
        total = e.get(PREFIJO + "TOTAL_CASOS")
        total = None if total in (None, "") else _numero(total, 1, 1000, "total_casos_no_valido", tipo=int)
        ttl = _numero(e.get(PREFIJO + "TTL_MIN", "20"), 1, 60, "ttl_no_valido", tipo=int) * 60
        max_logins = _numero(e.get(PREFIJO + "MAX_LOGINS", "3"), 1, 10, "max_logins_no_valido", tipo=int)
        ventana = _numero(e.get(PREFIJO + "VENTANA_LOGIN_MIN", "15"), 1, 120, "ventana_no_valida", tipo=int) * 60
        monitor = _monitor(e, token)
        cuentas = e.get(PREFIJO + "CUENTAS", "")
        if cuentas not in ("", "0", "1"):
            _rechazar("cuentas_no_valido")
        if cuentas == "1" and monitor is None:
            _rechazar("cuentas_sin_monitor")
        fcm = e.get(PREFIJO + "FCM_CUENTA_SERVICIO")
        if fcm not in (None, ""):
            if monitor is None:
                _rechazar("fcm_sin_monitor")
            fcm = _archivo(fcm, "fcm_cuenta_ausente_o_invalida", maximo=100_000)
        else:
            fcm = None
        clave_brevo, remitente_brevo = e.get(PREFIJO + "BREVO_CLAVE", ""), e.get(PREFIJO + "BREVO_REMITENTE", "")
        correo_api = None
        if clave_brevo or remitente_brevo:
            if not (clave_brevo and remitente_brevo):
                _rechazar("brevo_incompleto")
            if cuentas != "1":
                _rechazar("brevo_sin_cuentas")
            from tinotify.real_remoto.correo_brevo import CorreoNoValido, validar_clave_api
            from tinotify.real_remoto.cuentas import DatosNoValidos, normalizar_correo
            try:
                validar_clave_api(clave_brevo)
                remitente_brevo = normalizar_correo(remitente_brevo)
            except (CorreoNoValido, DatosNoValidos):
                _rechazar("brevo_no_valido")
            correo_api = (clave_brevo, remitente_brevo)
        return cls(modo=modo, token=token, tls=tls, correo_api=correo_api, proxies_confiables=proxies, tipo=tipo, total_casos=total,
                   acreditacion=_archivo(e.get(PREFIJO + "ACREDITACION_FILE", ""), "acreditacion_ausente"),
                   referencia=_archivo(e.get(PREFIJO + "REFERENCIA_FILE", ""), "referencia_ausente"),
                   ttl_s=ttl, max_logins=max_logins, ventana_login_s=ventana, monitor=monitor, fcm_cuenta=fcm, cuentas=cuentas == "1")


__all__ = ["Config", "ConfigMonitor", "ConfigPg", "clave_desde_texto", "ConfiguracionInsegura", "VariablesAjenas", "MODO_LOCAL", "MODO_REMOTO", "PROXIES_PRIVADAS", "TLS_DIRECTO", "TLS_PROXY"]
