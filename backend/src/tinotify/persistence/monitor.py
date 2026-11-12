"""Persistencia v2 de un único motor local, para un solo escritor."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID
import warnings

from tinotify.domain.actuaciones import (
    VERSION_HUELLA, EstadoReconciliacion,
    ResultadoReconciliacion, adaptar_observacion,
)
from tinotify.domain.identificadores import (
    ContextoOrigen, ContratoNoConfiable, IdentificadorCandidato,
    PoliticaConfianza, ReferenciaContrato,
)
from tinotify.domain.notificaciones import clasificar_prioridad, crear_notificacion
from tinotify.services.reconciliacion import reconciliar


class EstadoInvalido(ValueError):
    pass


class EstadoAntiguo(EstadoInvalido):
    pass


class TransicionRequerida(EstadoAntiguo):
    pass


REVISION_ESTADO = 2


def _nuevo_estado(migrado=False, politica=None, instancia="local"):
    politica = politica if politica is not None else PoliticaConfianza()
    return {
        "schema_version": 2, "state_revision": REVISION_ESTADO,
        "fingerprint_version": VERSION_HUELLA,
        "trust_policy": politica.firma(instancia),
        "migrated_from_v1": migrado, "cases": {},
    }


def _es_huella(valor):
    return isinstance(valor, str) and re.fullmatch(r"[0-9a-f]{64}", valor) is not None


def _caso(valor):
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        raise ValueError("Identificador de caso no válido.")
    clave = str(valor)
    if not clave.strip() or len(clave) > 128 or any(ord(c) < 32 for c in clave):
        raise ValueError("Identificador de caso no válido.")
    return clave


def _es_v1(estado):
    if not isinstance(estado, dict):
        return False
    try:
        return all(
            isinstance(k, str) and _caso(k) and isinstance(v, list) and all(_es_huella(h) for h in v)
            for k, v in estado.items()
        )
    except ValueError:
        return False


def _validar_v2(estado, *, anterior=False):
    try:
        claves = {"schema_version", "fingerprint_version", "migrated_from_v1", "cases"}
        if not anterior:
            claves |= {"state_revision", "trust_policy"}
        if not isinstance(estado, dict) or set(estado) != claves:
            raise ValueError
        if type(estado["schema_version"]) is not int or estado["schema_version"] != 2:
            raise ValueError
        if type(estado["fingerprint_version"]) is not int or estado["fingerprint_version"] != VERSION_HUELLA:
            raise ValueError
        if not anterior and (type(estado["state_revision"]) is not int or estado["state_revision"] != REVISION_ESTADO or not _es_huella(estado["trust_policy"])):
            raise ValueError
        if type(estado["migrated_from_v1"]) is not bool or not isinstance(estado["cases"], dict):
            raise ValueError
        locales = set()
        for clave, caso in estado["cases"].items():
            _caso(clave)
            if not isinstance(caso, dict) or set(caso) != {"records"} or not isinstance(caso["records"], list):
                raise ValueError
            origenes = set()
            for registro in caso["records"]:
                campos = {"local_id", "source_id", "version_hash", "status"}
                if not anterior:
                    campos |= {"contract_ref", "origin_scope"}
                if not isinstance(registro, dict) or set(registro) != campos:
                    raise ValueError
                local = registro["local_id"]
                if not isinstance(local, str) or str(UUID(local)) != local or local in locales:
                    raise ValueError
                locales.add(local)
                origen = registro["source_id"]
                if origen is not None:
                    IdentificadorCandidato(origen)
                    clave_origen = origen
                    if not anterior:
                        referencia, alcance = registro["contract_ref"], registro["origin_scope"]
                        if not isinstance(referencia, dict) or set(referencia) != {"clave", "version", "revision"}:
                            raise ValueError
                        ReferenciaContrato(**referencia)
                        if not isinstance(alcance, dict) or set(alcance) != {"instancia", "caso"}:
                            raise ValueError
                        ContextoOrigen(**alcance)
                        if alcance["caso"] != clave:
                            raise ValueError
                        clave_origen = (origen, referencia["clave"], referencia["version"], referencia["revision"], alcance["instancia"])
                    if clave_origen in origenes:
                        raise ValueError
                    origenes.add(clave_origen)
                elif not anterior and (registro["contract_ref"] is not None or registro["origin_scope"] is not None):
                    raise ValueError
                if not _es_huella(registro["version_hash"]):
                    raise ValueError
                clasificacion = EstadoReconciliacion(registro["status"])
                if not anterior and origen is None and clasificacion is EstadoReconciliacion.MODIFICADA:
                    raise ValueError
    except (ValueError, TypeError, AttributeError, KeyError):
        raise EstadoInvalido("Estado corrupto o versión no compatible; no se ha modificado.") from None


def _pares_unicos(pares):
    resultado = {}
    for clave, valor in pares:
        if clave in resultado:
            raise EstadoInvalido("El estado contiene claves repetidas.")
        resultado[clave] = valor
    return resultado


def _leer(ruta):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"), object_pairs_hook=_pares_unicos,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise EstadoInvalido("No se puede interpretar el estado; no se ha modificado.") from None


def _contenido(estado):
    _validar_v2(estado)
    return json.dumps(estado, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


class MonitorActuaciones:
    def __init__(self, archivo_estado="estado_monitor.json", *, politica_confianza=None, instancia_origen="local"):
        self.politica_confianza = politica_confianza if politica_confianza is not None else PoliticaConfianza()
        self.instancia_origen = instancia_origen
        self.archivo_estado = Path(archivo_estado)
        self._persistido = self.archivo_estado.exists()
        if not self._persistido:
            self.estado = _nuevo_estado(politica=self.politica_confianza, instancia=instancia_origen)
        else:
            estado = _leer(self.archivo_estado)
            self._validar_activo(estado)
            self.estado = estado

    def _validar_activo(self, estado):
        if _es_v1(estado):
            raise EstadoAntiguo("Estado v1 reconocido. Migra explícitamente a otro archivo antes de continuar.")
        if isinstance(estado, dict) and estado.get("schema_version") == 2 and "state_revision" not in estado:
            _validar_v2(estado, anterior=True)
            raise TransicionRequerida("V2 revisión 1 carece de evidencia de confianza. Transiciona explícitamente a otro archivo.")
        _validar_v2(estado)
        if estado["trust_policy"] != self.politica_confianza.firma(self.instancia_origen):
            raise TransicionRequerida("La política vigente cambió. Se requiere transición explícita y nueva línea base.")
        try:
            for caso, datos in estado["cases"].items():
                for registro in datos["records"]:
                    self.politica_confianza.desde_registro(registro, ContextoOrigen(self.instancia_origen, caso))
        except ContratoNoConfiable:
            raise TransicionRequerida("La identidad persistida no tiene un contrato vigente. Se requiere transición explícita.") from None

    def _comprobar_base(self):
        """Evita pisar un archivo alterado; no sustituye un bloqueo entre procesos."""
        self._validar_activo(self.estado)
        if self.archivo_estado.exists():
            actual = _leer(self.archivo_estado)
            self._validar_activo(actual)
            if actual != self.estado:
                raise EstadoInvalido("El estado cambió externamente; vuelve a cargarlo antes de continuar.")
        elif self._persistido:
            raise EstadoInvalido("El archivo de estado desapareció; no se recreará automáticamente.")

    @classmethod
    def migrar_estado_v1(cls, origen, destino, **configuracion):
        return cls._transicionar(origen, destino, solo_v1=True, **configuracion)

    @classmethod
    def transicionar_estado(cls, origen, destino, **configuracion):
        """V1, v2.1 o política anterior hacia v2.2 vacío, sin elevar confianza."""
        return cls._transicionar(origen, destino, solo_v1=False, **configuracion)

    @classmethod
    def _transicionar(cls, origen, destino, *, solo_v1, politica_confianza=None, instancia_origen="local"):
        origen, destino = Path(origen), Path(destino)
        if origen.resolve() == destino.resolve():
            raise ValueError("La migración requiere un archivo de destino diferente.")
        estado = _leer(origen)
        antiguo = _es_v1(estado)
        if solo_v1 and not antiguo:
            raise EstadoInvalido("El archivo de origen no es un estado v1 válido.")
        if not antiguo:
            _validar_v2(estado, anterior=isinstance(estado, dict) and "state_revision" not in estado)
        politica = politica_confianza if politica_confianza is not None else PoliticaConfianza()
        migrado_v1 = antiguo or estado["migrated_from_v1"]
        contenido = _contenido(_nuevo_estado(migrado=migrado_v1, politica=politica, instancia=instancia_origen))
        # Modo exclusivo: tampoco sobrescribir un destino corrupto o preexistente.
        with destino.open("x", encoding="utf-8") as archivo:
            try:
                archivo.write(contenido)
                archivo.flush()
                os.fsync(archivo.fileno())
            except BaseException:
                archivo.close()
                destino.unlink(missing_ok=True)
                raise
        warnings.warn("Se establecerá una nueva línea base sin avisos históricos; pueden omitirse novedades durante la migración.", UserWarning, stacklevel=2)
        return cls(destino, politica_confianza=politica, instancia_origen=instancia_origen)

    def _guardar_estado(self, estado):
        self._comprobar_base()
        contenido = _contenido(estado)
        fd, nombre = tempfile.mkstemp(prefix=self.archivo_estado.name + ".", suffix=".tmp", dir=self.archivo_estado.parent)
        temporal = Path(nombre)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as archivo:
                archivo.write(contenido)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, self.archivo_estado)
        finally:
            temporal.unlink(missing_ok=True)

    @staticmethod
    def identificar_actuacion(actuacion):
        """Huella LEGACY para compatibilidad; nunca alimenta el motor v2."""
        contenido = {campo: actuacion[campo] for campo in ("fecha", "direccion", "descripcion")}
        return hashlib.sha256(json.dumps(contenido, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def reconciliar(self, caso, actuaciones) -> ResultadoReconciliacion:
        self._comprobar_base()
        clave = _caso(caso)
        observaciones = [adaptar_observacion(a) for a in actuaciones]
        siguiente_caso, resultado = reconciliar(
            self.estado["cases"].get(clave), observaciones, caso=clave,
            instancia=self.instancia_origen, politica_confianza=self.politica_confianza,
        )
        siguiente = deepcopy(self.estado)
        siguiente["cases"][clave] = siguiente_caso
        if siguiente != self.estado:
            self._guardar_estado(siguiente)
            # Un fallo de escritura nunca adelanta el estado en memoria.
            self.estado = siguiente
            self._persistido = True
        return resultado

    @staticmethod
    def notificaciones(caso, resultado):
        # Se conserva cada evento interno y se agrupa el aviso genérico.
        avisos = {}
        for evento in resultado.eventos:
            prioridad = clasificar_prioridad(evento.direccion)
            clave = (evento.tipo.value, prioridad.value)
            avisos[clave] = crear_notificacion(caso, evento.direccion, evento.tipo)
        return [avisos[clave] for clave in sorted(avisos)]

    def sincronizar(self, caso, actuaciones):
        return self.notificaciones(caso, self.reconciliar(caso, actuaciones))
