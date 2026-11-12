"""Un solo motor puro: identidades de origen o coincidencias exactas con cantidad."""

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

from tinotify.domain.actuaciones import (
    Actuacion, ActuacionReconciliada, EstadoReconciliacion, EventoReconciliacion,
    ResultadoReconciliacion, TipoCambio,
)
from tinotify.domain.identificadores import (
    ContextoOrigen, PoliticaConfianza, clave_estable,
)


def reconciliar(
    estado_caso: dict | None, observaciones: list[Actuacion], *, caso: str,
    instancia: str = "local", politica_confianza: PoliticaConfianza | None = None,
) -> tuple[dict, ResultadoReconciliacion]:
    politica = politica_confianza if politica_confianza is not None else PoliticaConfianza()
    contexto = ContextoOrigen(instancia, caso)
    efectivas = [(a, politica.aplicar(a.identificador_origen, contexto)) for a in observaciones]
    ids = [clave_estable(i) for _, i in efectivas if clave_estable(i) is not None]
    if len(set(ids)) != len(ids):
        raise ValueError("Identificador de origen repetido en el mismo caso.")

    inicial = estado_caso is None
    registros = deepcopy(estado_caso["records"]) if estado_caso is not None else []
    por_origen = {
        clave_estable(politica.desde_registro(r, contexto)): r
        for r in registros if r["source_id"] is not None
    }
    anonimas = defaultdict(deque)
    for registro in sorted(registros, key=lambda r: r["local_id"]):
        if registro["source_id"] is None:
            anonimas[registro["version_hash"]].append(registro)

    emparejadas = []
    nuevas = []
    usadas = set()
    # Los duplicados exactos son ocurrencias indistinguibles, no identidades
    # físicas demostradas. El orden del historial no decide los emparejamientos.
    ordenadas = sorted(efectivas, key=lambda par: (clave_estable(par[1]) or (), par[0].huella_version))
    for actuacion, identificador in ordenadas:
        origen = clave_estable(identificador)
        version = actuacion.huella_version
        registro = por_origen.get(origen) if origen is not None else None
        if origen is None and anonimas[version]:
            registro = anonimas[version].popleft()
        if registro is None:
            nuevas.append((actuacion, identificador, version))
        else:
            usadas.add(registro["local_id"])
            emparejadas.append((actuacion, identificador, registro, version))

    ausentes = [r for r in registros if r["local_id"] not in usadas]
    faltan_anonimas = any(r["source_id"] is None for r in ausentes)
    faltan_conocidas = bool(ausentes)
    reconciliadas = []
    eventos = []

    def registrar(actuacion, identificador, registro, estado, tipo=None):
        reconciliadas.append(ActuacionReconciliada(
            registro["local_id"], identificador,
            registro["version_hash"], estado,
        ))
        if tipo is not None:
            registro["status"] = estado.value
            eventos.append(EventoReconciliacion(tipo, registro["local_id"], actuacion.direccion))

    for actuacion, identificador, registro, version in emparejadas:
        if registro["version_hash"] != version:
            registro["version_hash"] = version
            registrar(actuacion, identificador, registro, EstadoReconciliacion.MODIFICADA, TipoCambio.MODIFICACION_CONFIRMADA)
        else:
            # Repetir la misma consulta no resuelve una ambigüedad anterior.
            estado = EstadoReconciliacion.AMBIGUA if registro["status"] == EstadoReconciliacion.AMBIGUA.value else EstadoReconciliacion.SIN_CAMBIOS
            registrar(actuacion, identificador, registro, estado)

    for actuacion, identificador, version in nuevas:
        origen = clave_estable(identificador)
        ambigua = faltan_anonimas if origen is not None else faltan_conocidas
        if origen is not None:
            # Contratos distintos no demuestran que dos IDs pertenezcan a
            # actuaciones distintas ni que sean la misma. No cruzar namespaces.
            ambigua = ambigua or any(
                r["contract_ref"] != asdict(identificador.contrato) for r in ausentes
            )
        estado = EstadoReconciliacion.LINEA_BASE if inicial else (
            EstadoReconciliacion.AMBIGUA if ambigua else EstadoReconciliacion.PRIMERA_OBSERVACION
        )
        registro = {
            "local_id": str(uuid4()),
            "source_id": identificador.valor if origen is not None else None,
            "contract_ref": asdict(identificador.contrato) if origen is not None else None,
            "origin_scope": asdict(contexto) if origen is not None else None,
            "version_hash": version, "status": estado.value,
        }
        registros.append(registro)
        tipo = None if inicial else (TipoCambio.CAMBIO_AMBIGUO if ambigua else TipoCambio.PRIMERA_OBSERVACION)
        registrar(actuacion, identificador, registro, estado, tipo)

    # Se conservan registros ausentes: una consulta parcial no borra identidades.
    siguiente = {"records": sorted(registros, key=lambda r: r["local_id"])}
    return siguiente, ResultadoReconciliacion(tuple(reconciliadas), tuple(eventos))
