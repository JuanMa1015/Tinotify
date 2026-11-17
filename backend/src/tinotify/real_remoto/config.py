"""Configuración del backend remoto real. Todo se valida al arrancar y falla cerrado.

Los errores llevan un código estable, nunca valores. Aquí NO caben credenciales de SIGAC, de PostgreSQL ni de
Supabase: el servicio no tiene base de datos y las credenciales SIGAC solo existen en memoria durante un login.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from tinotify.real_remoto.comun import (
    MODO_LOCAL, MODO_REMOTO, PROXIES_PRIVADAS, TLS_DIRECTO, TLS_PROXY, ConfiguracionInsegura, _numero, _proxies,
    _rechazar, validar_token,
)

PREFIJO = "TINOTIFY_RR_"
VARIABLES = {PREFIJO + x for x in (
    "MODO", "TOKEN", "TLS", "PROXIES_CONFIABLES", "ACREDITACION_FILE", "REFERENCIA_FILE", "TIPO", "TOTAL_CASOS",
    "TTL_MIN", "MAX_LOGINS", "VENTANA_LOGIN_MIN")}
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
        return cls(modo=modo, token=token, tls=tls, proxies_confiables=proxies, tipo=tipo, total_casos=total,
                   acreditacion=_archivo(e.get(PREFIJO + "ACREDITACION_FILE", ""), "acreditacion_ausente"),
                   referencia=_archivo(e.get(PREFIJO + "REFERENCIA_FILE", ""), "referencia_ausente"),
                   ttl_s=ttl, max_logins=max_logins, ventana_login_s=ventana)


__all__ = ["Config", "ConfiguracionInsegura", "VariablesAjenas", "MODO_LOCAL", "MODO_REMOTO", "PROXIES_PRIVADAS", "TLS_DIRECTO", "TLS_PROXY"]
