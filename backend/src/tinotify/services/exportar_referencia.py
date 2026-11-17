"""Exportador LOCAL y de solo lectura de la referencia portable. No imprime identificadores ni contenido.

Lee v2 con `mode=ro&immutable=1` (nunca la modifica), deriva el número del caso acreditado comprobándolo contra el
contrato (HMAC), y escribe un archivo nuevo con solo las huellas con clave y los metadatos mínimos. No sobrescribe.
"""

import json
from pathlib import Path
import sqlite3
from uuid import UUID, uuid5

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.services.consulta_real_local import NAMESPACE_REAL, IdentidadExpedienteNoVerificada
from tinotify.services.politica_real_local import cargar_clave_acreditacion, politica_desde_clave
from tinotify.services.referencia_portable import ReferenciaPortableInvalida, construir, verificar

LIMITE_NUMERO = 10_000_000


def exportar(ruta_v2, ruta_clave, salida, *, politica=None, contrato=None):
    """`politica` y `contrato` solo los inyectan las pruebas; por defecto, los de producción."""
    clave = cargar_clave_acreditacion(ruta_clave)
    politica = politica or politica_desde_clave(clave)
    ruta_v2, salida = Path(ruta_v2).resolve(), Path(salida)
    if ruta_v2.suffix != ".sqlite3" or not ruta_v2.is_file():
        raise ReferenciaPortableInvalida("Almacén v2 no disponible")
    if salida.exists():
        raise ReferenciaPortableInvalida("La salida ya existe; no se sobrescribe")
    try:
        con = sqlite3.connect(f"{ruta_v2.as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            meta = dict(con.execute("SELECT clave, valor FROM meta"))
            if meta.get("esquema") != "2" or meta.get("perfil") != "real":
                raise ReferenciaPortableInvalida("El archivo no es un almacén real v2")
            filas = con.execute("SELECT id, caso, generacion, incluido FROM expedientes").fetchall()
            if len(filas) != 1 or not filas[0][3]:
                raise ReferenciaPortableInvalida("Se esperaba exactamente un expediente incluido")
            ident, caso, generacion, _ = filas[0]
            hashes = [f[0] for f in con.execute("SELECT version_hash FROM actuaciones WHERE expediente_id=? ORDER BY orden", (ident,))]
            eventos = con.execute("SELECT COUNT(*) FROM eventos WHERE expediente_id=?", (ident,)).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        raise ReferenciaPortableInvalida("El almacén v2 no tiene el formato esperado") from None
    numero = next((n for n in range(1, LIMITE_NUMERO) if str(uuid5(NAMESPACE_REAL, f"{INSTANCIA_REAL}:{n}")) == caso), None)
    if numero is None:
        raise ReferenciaPortableInvalida("No se pudo derivar el expediente")
    try:
        politica.exigir_expediente(numero, INSTANCIA_REAL)  # solo un expediente acreditado se exporta
    except Exception:
        raise IdentidadExpedienteNoVerificada("El expediente no está acreditado por esta clave") from None
    documento = construir(clave, instancia=INSTANCIA_REAL, numero=numero, version_hashes=hashes,
                          generacion=generacion, eventos_internos=eventos, contrato=contrato)
    verificar(clave, documento, instancia=INSTANCIA_REAL, contrato=contrato)  # comprobación de ida y vuelta antes de escribir
    salida.parent.mkdir(parents=True, exist_ok=True)
    with open(salida, "x", encoding="utf-8", newline="\n") as f:
        json.dump(documento, f, sort_keys=True, separators=(",", ":"))
    return {"huellas": len(documento["huellas"]), "huellas_distintas": len(set(documento["huellas"])),
            "generacion": generacion, "eventos_internos": eventos, "bytes": salida.stat().st_size}
