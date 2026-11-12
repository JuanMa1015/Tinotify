"""La confianza procede de una revisión del contrato, nunca del dato observado.

El catálogo se compone en código de confianza revisado. No se carga de estados,
payloads o variables de entorno. Actualmente producción NO tiene contratos.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType


def _texto(valor):
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 4096:
        raise ValueError("Metadatos de contrato no válidos.")


def _hash(valor):
    return hashlib.sha256(json.dumps(valor, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdentificadorCandidato:
    """Solo sintaxis y procedencia declarada; no demuestra estabilidad."""

    valor: str
    sistema: str = "sigac"
    mecanismo: str = "sin_contrato"

    def __post_init__(self):
        if not isinstance(self.valor, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.valor):
            raise ValueError("Identificador candidato no válido.")
        _texto(self.sistema)
        _texto(self.mecanismo)


# Compatibilidad nominal: el nombre anterior solo crea candidatos.
IdentificadorSigac = IdentificadorCandidato


class AlcanceUnicidad(str, Enum):
    CASO_EN_INSTANCIA = "caso_en_instancia"


class EstadoContrato(str, Enum):
    NO_REVISADO = "no_revisado"
    DESHABILITADO = "deshabilitado"
    HABILITADO = "habilitado"


class ContratoNoConfiable(ValueError):
    pass


@dataclass(frozen=True)
class EvidenciaRevision:
    documento: str
    huella_documento: str
    justificacion: str

    def __post_init__(self):
        _texto(self.documento)
        _texto(self.justificacion)
        if not isinstance(self.huella_documento, str) or not re.fullmatch(r"[0-9a-f]{64}", self.huella_documento):
            raise ValueError("Referencia de evidencia no válida.")


@dataclass(frozen=True)
class ReferenciaContrato:
    clave: str
    version: int
    revision: str

    def __post_init__(self):
        _texto(self.clave)
        if type(self.version) is not int or self.version < 1:
            raise ValueError("Versión de contrato no válida.")
        if not isinstance(self.revision, str) or not re.fullmatch(r"[0-9a-f]{64}", self.revision):
            raise ValueError("Revisión de contrato no válida.")


@dataclass(frozen=True)
class ContratoOrigen:
    """Descripción, no prueba autosuficiente de confianza.

    Solo una revisión externa real justifica incluirla en el catálogo de código
    confiable. Crear este objeto o rellenar evidencia ficticia no la habilita.
    """

    clave: str
    version: int
    sistema: str
    mecanismo: str
    alcance: AlcanceUnicidad
    garantias: tuple[str, ...]
    evidencia: EvidenciaRevision

    def __post_init__(self):
        for valor in (self.clave, self.sistema, self.mecanismo):
            _texto(valor)
        if type(self.version) is not int or self.version < 1:
            raise ValueError("Versión de contrato no válida.")
        if self.alcance is not AlcanceUnicidad.CASO_EN_INSTANCIA:
            raise ValueError("Alcance no soportado.")
        if not isinstance(self.garantias, tuple) or not self.garantias:
            raise ValueError("Faltan garantías justificadas.")
        for garantia in self.garantias:
            _texto(garantia)
        if not isinstance(self.evidencia, EvidenciaRevision):
            raise ValueError("Un booleano o configuración no constituye evidencia.")

    @property
    def referencia(self):
        # Vincula definición, alcance y evidencia. El hash no demuestra su verdad.
        return ReferenciaContrato(self.clave, self.version, _hash(asdict(self)))


@dataclass(frozen=True)
class ContextoOrigen:
    instancia: str
    caso: str

    def __post_init__(self):
        _texto(self.instancia)
        _texto(self.caso)


@dataclass(frozen=True)
class IdentificadorEstableVerificado:
    """Afirmación a revalidar contra la política vigente en cada operación."""

    candidato: IdentificadorCandidato
    contrato: ReferenciaContrato
    contexto: ContextoOrigen

    def __post_init__(self):
        if not isinstance(self.candidato, IdentificadorCandidato) or not isinstance(self.contrato, ReferenciaContrato) or not isinstance(self.contexto, ContextoOrigen):
            raise ValueError("Afirmación de identidad no válida.")

    @property
    def valor(self):
        return self.candidato.valor


class CatalogoContratosRevisados:
    """Frontera de confianza: solo composición de código previamente revisada.

    Nunca construir a partir de datos observados o persistidos. El constructor
    no realiza una auditoría ni puede demostrar garantías del sistema externo.
    """

    def __init__(self, contratos=()):
        referencias, versiones = {}, set()
        for contrato in contratos:
            if not isinstance(contrato, ContratoOrigen):
                raise ValueError("Definición de contrato no válida.")
            version = (contrato.clave, contrato.version)
            if version in versiones:
                raise ValueError("Versión de contrato repetida.")
            versiones.add(version)
            referencias[contrato.referencia] = contrato
        self._referencias = MappingProxyType(referencias)

    def buscar(self, referencia):
        return self._referencias.get(referencia)


class PoliticaConfianza:
    def __init__(self, catalogo=None, habilitados=()):
        self._catalogo = catalogo if catalogo is not None else CATALOGO_PRODUCCION
        if not isinstance(self._catalogo, CatalogoContratosRevisados):
            raise ValueError("La habilitación requiere el catálogo de código revisado.")
        try:
            self._habilitados = frozenset(habilitados)
        except TypeError:
            raise ValueError("La habilitación requiere referencias de contratos, no un booleano.") from None
        for referencia in self._habilitados:
            if not isinstance(referencia, ReferenciaContrato) or self._catalogo.buscar(referencia) is None:
                raise ContratoNoConfiable("La configuración no puede habilitar un contrato no revisado.")

    def estado(self, referencia):
        if self._catalogo.buscar(referencia) is None:
            return EstadoContrato.NO_REVISADO
        return EstadoContrato.HABILITADO if referencia in self._habilitados else EstadoContrato.DESHABILITADO

    def verificar(self, candidato, referencia, contexto):
        if self.estado(referencia) is not EstadoContrato.HABILITADO:
            raise ContratoNoConfiable("No hay un contrato revisado y habilitado para esta identidad.")
        contrato = self._catalogo.buscar(referencia)
        if not isinstance(candidato, IdentificadorCandidato) or not isinstance(contexto, ContextoOrigen):
            raise ContratoNoConfiable("Falta procedencia o alcance de identidad.")
        if (candidato.sistema, candidato.mecanismo) != (contrato.sistema, contrato.mecanismo):
            raise ContratoNoConfiable("La procedencia no coincide con el contrato.")
        return IdentificadorEstableVerificado(candidato, referencia, contexto)

    def aplicar(self, identificador, contexto):
        """Un envoltorio por sí solo no concede confianza ni cambia el alcance."""
        if not isinstance(identificador, IdentificadorEstableVerificado):
            return identificador
        if identificador.contexto != contexto:
            return identificador.candidato
        try:
            return self.verificar(identificador.candidato, identificador.contrato, contexto)
        except ContratoNoConfiable:
            return identificador.candidato

    def firma(self, instancia):
        """Huella de configuración; no firma criptográfica ni evidencia."""
        _texto(instancia)
        referencias = sorted((asdict(r) for r in self._habilitados), key=lambda r: (r["clave"], r["version"], r["revision"]))
        return _hash({"policy_version": 1, "instancia": instancia, "contratos": referencias})

    def desde_registro(self, registro, contexto):
        """El archivo aporta referencias, jamás el catálogo ni la evidencia."""
        try:
            if registro["source_id"] is None:
                return None
            referencia = ReferenciaContrato(**registro["contract_ref"])
            contrato = self._catalogo.buscar(referencia)
            if contrato is None or registro["origin_scope"] != asdict(contexto):
                raise ValueError
            candidato = IdentificadorCandidato(registro["source_id"], contrato.sistema, contrato.mecanismo)
            return self.verificar(candidato, referencia, contexto)
        except (KeyError, TypeError, ValueError):
            raise ContratoNoConfiable("La identidad persistida no está respaldada por el contrato y alcance vigentes.") from None


# No hay evidencia institucional suficiente: catálogo real vacío y cerrado por defecto.
CATALOGO_PRODUCCION = CatalogoContratosRevisados()


def clave_estable(identificador):
    if not isinstance(identificador, IdentificadorEstableVerificado):
        return None
    referencia, contexto = identificador.contrato, identificador.contexto
    return (referencia.clave, referencia.version, referencia.revision, contexto.instancia, contexto.caso, identificador.valor)
