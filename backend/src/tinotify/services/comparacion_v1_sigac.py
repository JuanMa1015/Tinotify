"""Comparación de UNA lectura real con las huellas del almacén local v1, solo lectura.

No escribe en ninguna base, no migra y no persiste la lectura. El archivo v1 se abre
únicamente con `mode=ro&immutable=1`. Solo se devuelven cantidades y booleanos: nunca
identificadores, nombres ni texto judicial.

Criterio: es una comprobación EMPÍRICA de continuidad observada. Que todas las huellas
previas (con multiplicidad) estén contenidas en la lectura actual indica que el número de
caso sigue señalando el mismo historial y que el algoritmo de huella sigue siendo
compatible. No prueba unicidad global ni ausencia de reutilización del número.
"""

from collections import Counter
from pathlib import Path
import re
import sqlite3

from tinotify.domain.actuaciones import VERSION_HUELLA
from tinotify.integrations.sigac.lectura_validada import _resolver_lectura, leer_historial_validado

_HEX64 = re.compile(r"[0-9a-f]{64}")
ESQUEMA_V1 = "1"
MAX_HUELLAS = 20000


class ComparacionNoPosible(ValueError):
    """El archivo v1 no tiene la forma esperada; no se compara nada."""


def leer_huellas_v1(ruta):
    """Multiconjunto de `version_hash` del único expediente v1. Lectura inmutable; sin contenido."""
    ruta = Path(ruta).resolve()
    if ruta.suffix != ".sqlite3" or not ruta.is_file():
        raise ComparacionNoPosible("Archivo v1 no disponible.")
    try:
        conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error:
        raise ComparacionNoPosible("No se pudo abrir el archivo v1 en solo lectura.") from None
    try:
        meta = dict(conexion.execute("SELECT clave, valor FROM meta"))
        if meta.get("esquema") != ESQUEMA_V1 or meta.get("perfil") != "real":
            raise ComparacionNoPosible("El archivo no es un almacén real de esquema v1.")
        expedientes = conexion.execute("SELECT id FROM expedientes").fetchall()
        if len(expedientes) != 1:
            raise ComparacionNoPosible("Se esperaba exactamente un expediente en v1.")
        huellas = [fila[0] for fila in conexion.execute(
            "SELECT version_hash FROM actuaciones WHERE expediente_id = ?", (expedientes[0][0],))]
    except sqlite3.Error:
        raise ComparacionNoPosible("El archivo v1 no tiene el formato esperado.") from None
    finally:
        conexion.close()
    if not huellas or len(huellas) > MAX_HUELLAS or any(not isinstance(h, str) or not _HEX64.fullmatch(h) for h in huellas):
        raise ComparacionNoPosible("Huellas v1 no válidas.")
    return Counter(huellas)


def comparar_huellas(previas, nuevas):
    """Compara multiconjuntos de huellas. Resultado: solo conteos y veredicto."""
    previas, nuevas = Counter(previas), Counter(nuevas)
    faltantes = previas - nuevas
    adicionales = nuevas - previas
    contenidas = sum(min(n, nuevas[h]) for h, n in previas.items())
    veredicto = "continuidad_observada" if previas and not faltantes else "rechazada"
    return {
        "version_huella_codigo": VERSION_HUELLA,
        "huellas_v1": previas.total(),
        "huellas_v1_distintas": len(previas),
        "huellas_v1_con_repeticion": sum(1 for n in previas.values() if n > 1),
        "huellas_lectura": nuevas.total(),
        "contenidas_con_multiplicidad": contenidas,
        "v1_ausentes_en_lectura": faltantes.total(),
        "adicionales_en_lectura": adicionales.total(),
        "huellas_compatibles": bool(previas) and contenidas > 0,
        "veredicto": veredicto,
    }


def ejecutar_comparacion(cliente, usuario, clave, *, tipo, total_casos, caso_numero, ruta_v1,
                         total_actuaciones=None, contenedor_id=None, caso_login=None):
    """Una autenticación, un listado, UNA lectura validada del caso pedido. No persiste nada."""
    previas = leer_huellas_v1(ruta_v1)  # antes de cualquier conexión: si v1 no sirve, no se consulta
    if type(caso_numero) is not int or caso_numero < 1 or type(total_casos) is not int or total_casos < 1:
        raise ValueError("Número de caso o total no válidos.")
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login)
    apariciones = [c.numero for c in casos].count(caso_numero)
    if apariciones != 1:
        return {"veredicto": "rechazada", "motivo": "caso_no_listado_o_repetido", "apariciones_en_listado": apariciones,
                "casos_listados": len(casos)}
    lectura = leer_historial_validado(cliente, caso_numero, total_esperado=total_actuaciones, contenedor_id=contenedor_id)
    _, actuaciones = _resolver_lectura(lectura)
    resumen = comparar_huellas(previas, (a.huella_version for a in actuaciones))
    return {**resumen, "apariciones_en_listado": apariciones, "casos_listados": len(casos),
            "detalle_validado": True, "persistencia": "ninguna", "v1_modificado": False}
