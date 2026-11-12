"""Observaciones y versiones de contenido; los hashes no son anonimización."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import unicodedata

from tinotify.domain.identificadores import (
    IdentificadorCandidato, IdentificadorEstableVerificado, IdentificadorSigac,
)


VERSION_HUELLA = 1


def texto_canonico(valor: str) -> str:
    if not isinstance(valor, str):
        raise ValueError("Se esperaba texto.")
    return unicodedata.normalize("NFC", valor.replace("\r\n", "\n").replace("\r", "\n"))


def serializar(valor: object) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def resumir(valor: object) -> str:
    return hashlib.sha256(serializar(valor).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Anexo:
    descripcion: str
    archivo: str
    referencia: str

    def contenido(self) -> dict[str, str]:
        return {campo: texto_canonico(getattr(self, campo)) for campo in ("descripcion", "archivo", "referencia")}


@dataclass(frozen=True)
class Actuacion:
    etapa: str
    origen: str
    destino: str
    fecha: datetime
    remitente: str
    descripcion: str
    # Compatibilidad de lectura con el parser anterior. Nunca es identidad v2.
    huella: str = ""
    anexos: tuple[Anexo, ...] = ()
    identificador_origen: IdentificadorCandidato | IdentificadorEstableVerificado | None = None

    def __post_init__(self):
        if not isinstance(self.fecha, datetime):
            raise ValueError("Fecha no válida.")
        for campo in ("etapa", "origen", "destino", "remitente", "descripcion"):
            texto_canonico(getattr(self, campo))
        if not isinstance(self.anexos, tuple) or any(not isinstance(a, Anexo) for a in self.anexos):
            raise ValueError("Metadatos de anexos no válidos.")
        if self.identificador_origen is not None and not isinstance(self.identificador_origen, (IdentificadorCandidato, IdentificadorEstableVerificado)):
            raise ValueError("Se requiere un identificador candidato o una afirmación verificable.")
        for anexo in self.anexos:
            anexo.contenido()

    def contenido_versionado(self) -> dict:
        return {
            "fingerprint_version": VERSION_HUELLA,
            "fecha": self.fecha.isoformat(),
            "etapa": texto_canonico(self.etapa),
            "origen": texto_canonico(self.origen).strip().upper(),
            "destino": texto_canonico(self.destino).strip().upper(),
            "remitente": texto_canonico(self.remitente),
            "descripcion": texto_canonico(self.descripcion),
            # El orden de presentación no importa; las repeticiones sí.
            "anexos": sorted((a.contenido() for a in self.anexos), key=serializar),
        }

    @property
    def huella_version(self) -> str:
        return resumir(self.contenido_versionado())

    @property
    def direccion(self) -> str:
        return f"{self.origen.strip().upper()}-->{self.destino.strip().upper()}"


class EstadoReconciliacion(str, Enum):
    LINEA_BASE = "linea_base"
    SIN_CAMBIOS = "sin_cambios"
    PRIMERA_OBSERVACION = "primera_observacion"
    MODIFICADA = "modificada"
    AMBIGUA = "ambigua"


class TipoCambio(str, Enum):
    PRIMERA_OBSERVACION = "primera_observacion"
    MODIFICACION_CONFIRMADA = "modificacion_confirmada"
    CAMBIO_AMBIGUO = "cambio_ambiguo"


@dataclass(frozen=True)
class ActuacionReconciliada:
    identidad_local: str
    identificador_origen: IdentificadorCandidato | IdentificadorEstableVerificado | None
    huella_version: str
    estado: EstadoReconciliacion


@dataclass(frozen=True)
class EventoReconciliacion:
    tipo: TipoCambio
    identidad_local: str
    direccion: str


@dataclass(frozen=True)
class ResultadoReconciliacion:
    actuaciones: tuple[ActuacionReconciliada, ...]
    eventos: tuple[EventoReconciliacion, ...]


def adaptar_observacion(valor: Actuacion | dict) -> Actuacion:
    """Compatibilidad con entradas mínimas antiguas; no inventa metadatos."""
    if isinstance(valor, Actuacion):
        return valor
    if not isinstance(valor, dict):
        raise ValueError("Observación no válida.")
    permitidos = {"fecha", "direccion", "descripcion", "etapa", "remitente", "anexos", "identificador_origen"}
    if set(valor) - permitidos or not {"fecha", "direccion", "descripcion"}.issubset(valor):
        raise ValueError("Campos de observación no válidos.")
    try:
        origen, destino = valor["direccion"].split("-->")
        if not origen.strip() or not destino.strip():
            raise ValueError
        fecha = valor["fecha"]
        if isinstance(fecha, str):
            fecha = datetime.fromisoformat(fecha)
        return Actuacion(
            etapa=valor.get("etapa", ""), origen=origen, destino=destino,
            fecha=fecha, remitente=valor.get("remitente", ""), descripcion=valor["descripcion"],
            anexos=tuple(valor.get("anexos", ())), identificador_origen=valor.get("identificador_origen"),
        )
    except (TypeError, AttributeError, ValueError):
        raise ValueError("Observación no válida.") from None
