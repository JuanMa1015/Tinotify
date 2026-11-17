"""La confianza procede de una revisión del contrato, nunca del dato observado.

El catálogo se compone en código de confianza revisado. No se carga de estados,
payloads o variables de entorno. Producción no tiene contratos de actuación; solo uno de expediente (continuidad observada, un expediente).
"""

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import hmac
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


class AlcanceExpediente(str, Enum):
    """Único alcance demostrable: continuidad OBSERVADA dentro de una instancia.

    No es unicidad global ni descarta que SIGAC reutilice o renumere un número.
    """

    CONTINUIDAD_OBSERVADA_EN_INSTANCIA = "continuidad_observada_en_instancia"


# Afirmaciones que ningún contrato de expediente puede hacer ni omitir negar.
NO_GARANTIZADO_OBLIGATORIO = ("unicidad_global", "ausencia_de_reutilizacion")


@dataclass(frozen=True)
class ContratoExpediente:
    """Descripción (no prueba) de que «Caso Nro. N» identifica de forma continua
    un expediente dentro de una instancia SIGAC, según lecturas reales revisadas.

    Declara explícitamente lo que NO garantiza. Crear este objeto no lo habilita:
    solo un catálogo de código revisado y una política que lo nombre lo hacen.
    """

    clave: str
    version: int
    sistema: str
    mecanismo: str
    alcance: AlcanceExpediente
    garantias: tuple[str, ...]
    no_garantiza: tuple[str, ...]
    evidencia: EvidenciaRevision
    # Compromisos HMAC de los expedientes acreditados (ver `compromiso_expediente`). Falla cerrado: sin
    # compromisos el contrato no se aplica a ningún expediente, y el número nunca consta en el código.
    expedientes_acreditados: tuple[str, ...] = ()

    def __post_init__(self):
        for valor in (self.clave, self.sistema, self.mecanismo):
            _texto(valor)
        if type(self.version) is not int or self.version < 1:
            raise ValueError("Versión de contrato no válida.")
        if (not isinstance(self.expedientes_acreditados, tuple) or not self.expedientes_acreditados
                or any(not isinstance(c, str) or not re.fullmatch(r"[0-9a-f]{64}", c) for c in self.expedientes_acreditados)):
            raise ValueError("El contrato exige compromisos de expedientes acreditados.")
        if self.alcance is not AlcanceExpediente.CONTINUIDAD_OBSERVADA_EN_INSTANCIA:
            raise ValueError("Alcance no soportado.")
        for campo in (self.garantias, self.no_garantiza):
            if not isinstance(campo, tuple) or not campo:
                raise ValueError("Faltan garantías o límites justificados.")
            for texto in campo:
                _texto(texto)
        if set(NO_GARANTIZADO_OBLIGATORIO) & set(self.garantias):
            raise ValueError("Un contrato de expediente no puede afirmar unicidad global ni ausencia de reutilización.")
        if not set(NO_GARANTIZADO_OBLIGATORIO) <= set(self.no_garantiza):
            raise ValueError("El contrato debe declarar que no garantiza unicidad global ni ausencia de reutilización.")
        if not isinstance(self.evidencia, EvidenciaRevision):
            raise ValueError("Un booleano o configuración no constituye evidencia.")

    @property
    def referencia(self):
        return ReferenciaContrato(self.clave, self.version, _hash(asdict(self)))


def compromiso_expediente(clave_acreditacion, instancia, contrato_clave, numero):
    """HMAC-SHA256 del número de caso con una clave local secreta (nunca versionada).

    Permite acreditar expedientes concretos sin escribir su número en el código ni dejar un hash
    enumerable. Sin la clave local no se puede ni verificar ni reconstruir.
    """
    if not isinstance(clave_acreditacion, (bytes, bytearray)) or len(clave_acreditacion) < 16:
        raise ValueError("Clave de acreditación no válida.")
    if type(numero) is not int or numero < 1:
        raise ValueError("Número de expediente no válido.")
    _texto(instancia)
    _texto(contrato_clave)
    return hmac.new(bytes(clave_acreditacion), f"{instancia}|{contrato_clave}|{numero}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ExpedienteVerificado:
    """Resultado de revalidar, en cada operación, un número de caso en su instancia."""

    numero: int
    instancia: str
    contrato: ReferenciaContrato

    def __post_init__(self):
        if type(self.numero) is not int or self.numero < 1:
            raise ValueError("Número de expediente no válido.")
        _texto(self.instancia)
        if not isinstance(self.contrato, ReferenciaContrato):
            raise ValueError("Afirmación de expediente no válida.")


class CatalogoContratosRevisados:
    """Frontera de confianza: solo composición de código previamente revisada.

    Nunca construir a partir de datos observados o persistidos. El constructor
    no realiza una auditoría ni puede demostrar garantías del sistema externo.
    """

    def __init__(self, contratos=(), expedientes=()):
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
        exp_refs, exp_versiones = {}, set()
        for contrato in expedientes:
            if not isinstance(contrato, ContratoExpediente):
                raise ValueError("Definición de contrato de expediente no válida.")
            version = (contrato.clave, contrato.version)
            if version in exp_versiones or version in versiones:
                raise ValueError("Versión de contrato repetida.")
            exp_versiones.add(version)
            exp_refs[contrato.referencia] = contrato
        self._expedientes = MappingProxyType(exp_refs)

    def buscar(self, referencia):
        return self._referencias.get(referencia)

    def buscar_expediente(self, referencia):
        return self._expedientes.get(referencia)


class PoliticaConfianza:
    def __init__(self, catalogo=None, habilitados=(), expedientes_habilitados=(), clave_acreditacion=None):
        # Solo verifica compromisos; por sí sola no concede ni cambia la firma de la política.
        self._clave_acreditacion = bytes(clave_acreditacion) if clave_acreditacion is not None else None
        self._catalogo = catalogo if catalogo is not None else CATALOGO_PRODUCCION
        if not isinstance(self._catalogo, CatalogoContratosRevisados):
            raise ValueError("La habilitación requiere el catálogo de código revisado.")
        try:
            self._habilitados = frozenset(habilitados)
            self._expedientes_habilitados = frozenset(expedientes_habilitados)
        except TypeError:
            raise ValueError("La habilitación requiere referencias de contratos, no un booleano.") from None
        for referencia in self._habilitados:
            if not isinstance(referencia, ReferenciaContrato) or self._catalogo.buscar(referencia) is None:
                raise ContratoNoConfiable("La configuración no puede habilitar un contrato no revisado.")
        for referencia in self._expedientes_habilitados:
            if not isinstance(referencia, ReferenciaContrato) or self._catalogo.buscar_expediente(referencia) is None:
                raise ContratoNoConfiable("La configuración no puede habilitar un contrato de expediente no revisado.")

    def estado_expediente(self, referencia):
        if self._catalogo.buscar_expediente(referencia) is None:
            return EstadoContrato.NO_REVISADO
        return EstadoContrato.HABILITADO if referencia in self._expedientes_habilitados else EstadoContrato.DESHABILITADO

    @property
    def tiene_contrato_expediente(self):
        return bool(self._expedientes_habilitados)

    def exigir_expediente(self, numero, instancia, sistema="sigac"):
        """Revalida el número contra la política vigente; sin contrato habilitado, falla."""
        if type(numero) is not int or numero < 1:
            raise ContratoNoConfiable("Número de expediente no válido.")
        try:
            _texto(instancia)
        except ValueError:
            raise ContratoNoConfiable("Instancia no válida.") from None
        for referencia in sorted(self._expedientes_habilitados, key=lambda r: (r.clave, r.version, r.revision)):
            contrato = self._catalogo.buscar_expediente(referencia)
            if contrato is None or contrato.sistema != sistema or self._clave_acreditacion is None:
                continue
            try:
                compromiso = compromiso_expediente(self._clave_acreditacion, instancia, contrato.clave, numero)
            except ValueError:
                continue
            if any(hmac.compare_digest(compromiso, c) for c in contrato.expedientes_acreditados):
                return ExpedienteVerificado(numero, instancia, referencia)
        raise ContratoNoConfiable("No hay un contrato de expediente revisado y habilitado.")

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
        base = {"policy_version": 1, "instancia": instancia, "contratos": referencias}
        if self._expedientes_habilitados:
            # Solo si existe; sin contratos de expediente la firma histórica no cambia.
            base["expedientes"] = sorted((asdict(r) for r in self._expedientes_habilitados),
                                         key=lambda r: (r["clave"], r["version"], r["revision"]))
        return _hash(base)

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


# Contrato de continuidad OBSERVADA de «Caso Nro. N» en la instancia SIGAC, acreditado por UNA comparación real
# autorizada (docs/evidencia/comparacion-v1-sigac-continuidad.json; la huella es la de su JSON canónico:
# sort_keys, separadores compactos). No declara unicidad global ni ausencia de reutilización, y se aplica solo a los
# expedientes de `expedientes_acreditados` (compromisos HMAC; el número no consta en el código). Tener el contrato en
# el catálogo no lo habilita: la política debe nombrarlo y disponer de la clave local de acreditación.
CONTRATO_CASO_NRO_CONTINUIDAD = ContratoExpediente(
    clave="sigac-caso-nro-continuidad", version=1, sistema="sigac", mecanismo="caso_nro_hidcaso",
    alcance=AlcanceExpediente.CONTINUIDAD_OBSERVADA_EN_INSTANCIA,
    garantias=("en una lectura real posterior el mismo número devolvió el mismo historial: 709 de 709 huellas, con multiplicidad",
               "el número apareció exactamente una vez en el listado y el detalle validó el mismo número"),
    no_garantiza=("unicidad_global", "ausencia_de_reutilizacion", "estabilidad_futura_del_numero"),
    evidencia=EvidenciaRevision(
        "docs/evidencia/comparacion-v1-sigac-continuidad.json",
        "8e2fde33993d49e88424e24610ce8693a3f851cab7219d17e5c9eb91d069f11b",
        "Una comparación real autorizada entre la lectura actual y las huellas del almacén v1; solo conteos."),
    expedientes_acreditados=("b526d93c8f03265f17b1ac83ca718d4714a17d29437557c22a5758262b7b62d9",),
)

# Catálogo de producción: sin contratos de actuación; un único contrato de expediente, limitado a un expediente.
CATALOGO_PRODUCCION = CatalogoContratosRevisados(expedientes=(CONTRATO_CASO_NRO_CONTINUIDAD,))


def clave_estable(identificador):
    if not isinstance(identificador, IdentificadorEstableVerificado):
        return None
    referencia, contexto = identificador.contrato, identificador.contexto
    return (referencia.clave, referencia.version, referencia.revision, contexto.instancia, contexto.caso, identificador.valor)
