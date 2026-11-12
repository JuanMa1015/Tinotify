"""Todas las observaciones adicionales son sintéticas."""

from dataclasses import replace
from datetime import datetime

import pytest

from tinotify.domain.actuaciones import Actuacion, Anexo
from tinotify.domain.identificadores import (
    AlcanceUnicidad, CatalogoContratosRevisados, ContextoOrigen, ContratoOrigen,
    EvidenciaRevision, IdentificadorCandidato, PoliticaConfianza,
)
from tinotify.persistence.monitor import MonitorActuaciones


@pytest.fixture
def contrato_sintetico():
    # Evidencia exclusivamente ficticia para probar la frontera de confianza.
    return ContratoOrigen(
        clave="contrato-pruebas", version=1, sistema="sistema-ficticio",
        mecanismo="registro.id", alcance=AlcanceUnicidad.CASO_EN_INSTANCIA,
        garantias=("ID ficticio no reutilizado dentro del caso e instancia",),
        evidencia=EvidenciaRevision("documento-ficticio-de-prueba", "0" * 64, "Modelo sintético controlado por la prueba"),
    )


@pytest.fixture
def politica_sintetica(contrato_sintetico):
    catalogo = CatalogoContratosRevisados((contrato_sintetico,))
    return PoliticaConfianza(catalogo, (contrato_sintetico.referencia,))


@pytest.fixture
def monitor_ficticio(politica_sintetica):
    class FabricaPruebas:
        def __call__(self, *args, **kwargs):
            kwargs.setdefault("politica_confianza", politica_sintetica)
            return MonitorActuaciones(*args, **kwargs)

        def migrar_estado_v1(self, origen, destino):
            return MonitorActuaciones.migrar_estado_v1(origen, destino, politica_confianza=politica_sintetica)

    return FabricaPruebas()


@pytest.fixture
def anexo_ficticio():
    return Anexo("ANEXO FICTICIO", "archivo_ficticio.txt", "general.descargarAnexo.con?codigo=FICTICIO")


@pytest.fixture
def actuacion_ficticia(politica_sintetica, contrato_sintetico):
    base = Actuacion(
        etapa="ETAPA FICTICIA", origen="ASESOR", destino="ESTUDIANTE",
        fecha=datetime(2020, 1, 1, 10), remitente="REMITENTE FICTICIO",
        descripcion="DESCRIPCIÓN FICTICIA",
    )

    def crear(id_origen=None, caso_origen="CASO_FICTICIO", instancia_origen="local", **cambios):
        if id_origen is not None:
            candidato = IdentificadorCandidato(id_origen, "sistema-ficticio", "registro.id")
            cambios["identificador_origen"] = politica_sintetica.verificar(
                candidato, contrato_sintetico.referencia, ContextoOrigen(instancia_origen, caso_origen),
            )
        return replace(base, **cambios)

    return crear
