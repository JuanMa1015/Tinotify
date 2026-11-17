"""Monitor real: lectura de TODOS los expedientes accesibles y comparación contra el estado guardado.

Solo se compara y se guarda lo mínimo: por expediente, el multiconjunto de huellas CON CLAVE (HMAC) de sus actuaciones y unos
conteos. Nunca se conserva texto judicial. La lógica de comparación (`planificar`) es una función pura, sin red ni base de datos.

Reglas:
- Sin estado previo en absoluto (primera ejecución): línea base silenciosa para todos los expedientes, salvo el acreditado, que
  parte de la referencia portable (todo lo posterior a esa referencia SÍ es novedad).
- Expediente nuevo en ejecuciones posteriores: se registra su línea base (sus actuaciones antiguas NO son novedades) y se avisa solo de
  que apareció un expediente.
- Novedad = huellas actuales menos huellas previas (con multiplicidad). Si falta alguna huella previa, la lectura es dudosa: no se
  notifican novedades ni se sobrescribe el estado; se marca una anomalía (avisada solo al producirse).
- Un expediente que deja de aparecer en el listado no cambia nada.
"""

from collections import Counter
from dataclasses import dataclass
import hashlib
import hmac

from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, leer_historial_validado
from tinotify.integrations.sigac.sigac_client import SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.services.referencia_portable import _sub, huella_portable

MAX_EXPEDIENTES = 200


def caso_ref(clave_acreditacion, instancia, numero):
    """Identificador opaco (HMAC-SHA256, 64 hex) del expediente. No permite recuperar el número sin la clave."""
    return hmac.new(_sub(clave_acreditacion, "monitor-caso"), f"{instancia}|{numero}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class EstadoPrevio:
    huellas: Counter
    acreditado: bool = False
    generacion: int = 1
    anomalia: bool = False


@dataclass(frozen=True)
class Cambio:
    caso_ref: str
    accion: str            # nuevo | sin_cambios | novedades | anomalia
    huellas: Counter       # estado a conservar tras aplicar (el previo si es anomalía)
    novedades: int
    acreditado: bool
    generacion: int
    anomalia: bool
    en_bd: bool            # False: hay que insertar el expediente completo


@dataclass(frozen=True)
class Plan:
    cambios: tuple
    expedientes: int
    novedades: int
    expedientes_con_novedades: int
    expedientes_nuevos: int
    anomalias: int
    primera_ejecucion: bool

    @property
    def requiere_aviso(self):
        return self.novedades > 0 or self.expedientes_nuevos > 0 or self.anomalias > 0

    @property
    def resultado(self):
        if self.anomalias:
            return "anomalia"
        return "linea_base" if self.primera_ejecucion and not self.novedades else "ok"


def planificar(previos, lecturas, semillas=None):
    """`previos`: {caso_ref: EstadoPrevio} de la base; `lecturas`: {caso_ref: Counter}; `semillas`: {caso_ref: Counter} del
    expediente acreditado (solo cuentan si no hay NINGÚN estado previo)."""
    semillas = semillas or {}
    primera = not previos
    efectivos = dict(previos)
    if primera:
        for ref, huellas in semillas.items():
            efectivos[ref] = EstadoPrevio(huellas=Counter(huellas), acreditado=True)
    cambios, novedades, con_novedades, nuevos, anomalias = [], 0, 0, 0, 0
    for ref in sorted(lecturas):
        actual = Counter(lecturas[ref])
        previo = efectivos.get(ref)
        en_bd = ref in previos
        if previo is None:
            cambios.append(Cambio(ref, "nuevo", actual, 0, False, 1, False, False))
            if not primera:
                nuevos += 1
            continue
        faltantes, nuevas = previo.huellas - actual, actual - previo.huellas
        if faltantes:
            if not previo.anomalia:
                anomalias += 1  # solo al producirse: una anomalía persistente no repite el aviso
            cambios.append(Cambio(ref, "anomalia", Counter(previo.huellas), 0, previo.acreditado, previo.generacion, True, en_bd))
        elif nuevas:
            n = nuevas.total()
            novedades += n
            con_novedades += 1
            cambios.append(Cambio(ref, "novedades", actual, n, previo.acreditado, previo.generacion + 1, False, en_bd))
        else:
            cambios.append(Cambio(ref, "sin_cambios", actual, 0, previo.acreditado, previo.generacion, False, en_bd))
    return Plan(tuple(cambios), len(lecturas), novedades, con_novedades, nuevos, anomalias, primera)


def leer_expedientes(cliente, usuario, clave, *, tipo, total_casos, caso_login, clave_acreditacion, instancia,
                     max_expedientes=MAX_EXPEDIENTES):
    """Una autenticación y una lectura validada por expediente. Devuelve ({caso_ref: Counter}, fallidos, listados).

    Un expediente que falla (salvo por sesión caducada, que aborta todo) se omite y su estado no cambia. Un historial vacío es un
    estado válido (así su primera actuación sí será novedad)."""
    opciones = {"listado_estructural": True} if total_casos is None else {}
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login, **opciones)
    if len(casos) > max_expedientes:
        raise SigacClientError("Demasiados expedientes.", codigo=CodigoHistorial.LISTADO_NO_CONFIRMADO)
    lecturas, fallidos = {}, 0
    for caso in casos:
        ref = caso_ref(clave_acreditacion, instancia, caso.numero)
        try:
            _, actuaciones = _resolver_lectura(leer_historial_validado(cliente, caso.numero))
            lecturas[ref] = Counter(huella_portable(clave_acreditacion, a.huella_version) for a in actuaciones)
        except SigacSessionExpired:
            raise
        except SigacClientError as error:
            if error.codigo is CodigoHistorial.SIN_ACTUACIONES:
                lecturas[ref] = Counter()
            else:
                fallidos += 1
    return lecturas, fallidos, len(casos)
