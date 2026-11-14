"""Correspondencia sin perdida con v2.2; bytea preserva UTF-8 surrogatepass."""

from tinotify.domain.identificadores import ContextoOrigen, PoliticaConfianza
from tinotify.persistence.monitor import _nuevo_estado, _validar_v2, TransicionRequerida


def binario(texto: str) -> bytes:
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("Clave no valida")
    valor = texto.encode("utf-8", "surrogatepass")
    if len(valor) > 512:
        raise ValueError("La clave excede el limite PostgreSQL; no se ha truncado")
    return valor


def texto(bytea: str) -> str:
    return bytes.fromhex(bytea.removeprefix("\\x")).decode("utf-8", "surrogatepass")


def validar_confianza(estado: dict, politica: PoliticaConfianza, instancia: str) -> None:
    _validar_v2(estado)
    if estado["trust_policy"] != politica.firma(instancia):
        raise TransicionRequerida("Politica incompatible; transicion explicita requerida")
    for caso, datos in estado["cases"].items():
        for registro in datos["records"]:
            politica.desde_registro(registro, ContextoOrigen(instancia, caso))


def a_filas(registros: list[dict]) -> list[dict]:
    filas = []
    for orden, registro in enumerate(registros):
        contrato, alcance = registro["contract_ref"], registro["origin_scope"]
        filas.append({
            "local_id": registro["local_id"], "orden_registro": orden,
            "version_hash": registro["version_hash"], "status": registro["status"],
            "source_id": registro["source_id"],
            "contrato_clave_utf8": "\\x"+binario(contrato["clave"]).hex() if contrato else None,
            "contrato_version_decimal": str(contrato["version"]) if contrato else None,
            "contrato_revision": contrato["revision"] if contrato else None,
            "alcance_instancia_utf8": "\\x"+binario(alcance["instancia"]).hex() if alcance else None,
            "alcance_caso_utf8": "\\x"+binario(alcance["caso"]).hex() if alcance else None,
        })
    return filas


def de_filas(filas: list[dict]) -> dict:
    registros = []
    for fila in filas:
        contrato = None if fila["source_id"] is None else {
            "clave": texto(fila["contrato_clave_utf8"]),
            "version": int(fila["contrato_version_decimal"]),
            "revision": fila["contrato_revision"],
        }
        alcance = None if contrato is None else {
            "instancia": texto(fila["alcance_instancia_utf8"]),
            "caso": texto(fila["alcance_caso_utf8"]),
        }
        registros.append({
            "local_id": fila["local_id"], "source_id": fila["source_id"],
            "contract_ref": contrato, "origin_scope": alcance,
            "version_hash": fila["version_hash"], "status": fila["status"],
        })
    return {"records": registros}


def reconstruir(datos: dict, instancia: str, politica: PoliticaConfianza) -> dict:
    cabecera = datos["cabecera"]
    estado = _nuevo_estado(politica=politica, instancia=instancia)
    for campo in ("schema_version", "state_revision", "fingerprint_version", "trust_policy", "migrated_from_v1"):
        estado[campo] = cabecera[campo]
    estado["cases"] = {texto(caso["clave"]): de_filas(caso["records"]) for caso in datos["casos"]}
    validar_confianza(estado, politica, instancia)
    return estado
