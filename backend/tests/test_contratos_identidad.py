from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from tinotify.domain.actuaciones import EstadoReconciliacion, TipoCambio
from tinotify.domain.identificadores import (
    AlcanceUnicidad, CatalogoContratosRevisados, ContextoOrigen, ContratoNoConfiable,
    EstadoContrato, IdentificadorCandidato, IdentificadorEstableVerificado,
    IdentificadorSigac, PoliticaConfianza, ReferenciaContrato,
)
from tinotify.persistence.monitor import (
    EstadoInvalido, MonitorActuaciones, TransicionRequerida,
)
from tinotify.services.reconciliacion import reconciliar


def _edicion_sin_confirmacion(ruta, actuacion, politica=None, caso="CASO_FICTICIO", instancia="local"):
    monitor = MonitorActuaciones(ruta, politica_confianza=politica, instancia_origen=instancia)
    monitor.reconciliar(caso, [actuacion])
    resultado = monitor.reconciliar(caso, [replace(actuacion, descripcion="EDICIÓN FICTICIA")])
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.CAMBIO_AMBIGUO]
    assert isinstance(resultado.actuaciones[0].identificador_origen, IdentificadorCandidato)
    assert not isinstance(resultado.actuaciones[0].identificador_origen, IdentificadorEstableVerificado)
    assert not monitor.reconciliar(caso, [replace(actuacion, descripcion="EDICIÓN FICTICIA")]).eventos
    return monitor


def test_sintaxis_sigac_nunca_es_prueba_de_estabilidad(tmp_path, actuacion_ficticia):
    candidato = IdentificadorSigac("SIGAC-FICTICIO-A")
    a = actuacion_ficticia(identificador_origen=candidato)
    m = _edicion_sin_confirmacion(tmp_path / "estado.json", a)
    assert all(r["source_id"] is None and r["contract_ref"] is None for r in m.estado["cases"]["CASO_FICTICIO"]["records"])


@pytest.mark.parametrize("contenidos_iguales", [False, True])
def test_candidato_repetido_no_demuestra_identidad(tmp_path, actuacion_ficticia, contenidos_iguales):
    a = actuacion_ficticia(identificador_origen=IdentificadorSigac("SIGAC-FICTICIO-A"))
    b = a if contenidos_iguales else replace(a, descripcion="OTRA FICTICIA")
    m = MonitorActuaciones(tmp_path / "estado.json")
    resultado = m.reconciliar("CASO_FICTICIO", [a, b])
    assert len({r.identidad_local for r in resultado.actuaciones}) == 2
    assert not resultado.eventos


def test_envoltorio_verificado_no_concede_confianza_por_si_solo(tmp_path, actuacion_ficticia):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    assert isinstance(a.identificador_origen, IdentificadorEstableVerificado)
    _edicion_sin_confirmacion(tmp_path / "estado.json", a)


def test_configuracion_no_crea_evidencia(contrato_sintetico, monkeypatch):
    monkeypatch.setenv("TINOTIFY_ENABLE_STABLE_IDS", "true")
    politica = PoliticaConfianza()
    assert politica.estado(contrato_sintetico.referencia) == EstadoContrato.NO_REVISADO
    with pytest.raises(ContratoNoConfiable):
        PoliticaConfianza(habilitados=(contrato_sintetico.referencia,))


@pytest.mark.parametrize("evidencia", [True, False, "revisado", None])
def test_evidencia_no_es_booleano_o_declaracion_libre(contrato_sintetico, evidencia):
    with pytest.raises(ValueError): replace(contrato_sintetico, evidencia=evidencia)


@pytest.mark.parametrize("cambios", [
    {"version": True}, {"version": 0}, {"alcance": "global"}, {"garantias": ()}, {"garantias": (True,)},
])
def test_definicion_de_contrato_invalida_rechazada(contrato_sintetico, cambios):
    with pytest.raises(ValueError): replace(contrato_sintetico, **cambios)


def test_catalogo_revisado_y_habilitacion_son_decisiones_separadas(contrato_sintetico):
    catalogo = CatalogoContratosRevisados((contrato_sintetico,))
    ref = contrato_sintetico.referencia
    assert PoliticaConfianza(catalogo).estado(ref) == EstadoContrato.DESHABILITADO
    assert PoliticaConfianza(catalogo, (ref,)).estado(ref) == EstadoContrato.HABILITADO
    with pytest.raises(ValueError): PoliticaConfianza(catalogo=True)
    with pytest.raises(ValueError): PoliticaConfianza(catalogo, habilitados=True)


def test_catalogo_no_acepta_revisiones_conflictivas_de_la_misma_version(contrato_sintetico):
    otro = replace(contrato_sintetico, mecanismo="otro.campo")
    with pytest.raises(ValueError): CatalogoContratosRevisados((contrato_sintetico, otro))


@pytest.mark.parametrize("cambio", ["version", "evidencia", "mecanismo", "garantias"])
def test_referencia_vincula_version_definicion_y_evidencia(contrato_sintetico, cambio):
    cambios = {
        "version": {"version": 2},
        "evidencia": {"evidencia": replace(contrato_sintetico.evidencia, justificacion="OTRA JUSTIFICACIÓN FICTICIA")},
        "mecanismo": {"mecanismo": "otro.campo"},
        "garantias": {"garantias": ("OTRA GARANTÍA FICTICIA",)},
    }
    cambiado = replace(contrato_sintetico, **cambios[cambio])
    assert cambiado.referencia != contrato_sintetico.referencia
    politica = PoliticaConfianza(CatalogoContratosRevisados((cambiado,)), (cambiado.referencia,))
    candidato = IdentificadorCandidato("FICTICIO-A", cambiado.sistema, cambiado.mecanismo)
    with pytest.raises(ContratoNoConfiable): politica.verificar(candidato, contrato_sintetico.referencia, ContextoOrigen("local", "CASO_FICTICIO"))


def test_contrato_vigente_confirma_solo_en_su_contexto(tmp_path, actuacion_ficticia, politica_sintetica):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    m = MonitorActuaciones(tmp_path / "estado.json", politica_confianza=politica_sintetica)
    original = m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [replace(a, descripcion="EDICIÓN FICTICIA")])
    assert resultado.eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA
    assert resultado.actuaciones[0].identidad_local == original.actuaciones[0].identidad_local


@pytest.mark.parametrize("desajuste", ["caso", "instancia", "sistema", "mecanismo", "revision", "version"])
def test_afirmacion_incompatible_no_confirma(tmp_path, actuacion_ficticia, politica_sintetica, desajuste):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    identificador = a.identificador_origen
    if desajuste == "caso": identificador = replace(identificador, contexto=ContextoOrigen("local", "OTRO_CASO_FICTICIO"))
    elif desajuste == "instancia": identificador = replace(identificador, contexto=ContextoOrigen("otra-instancia", "CASO_FICTICIO"))
    elif desajuste == "sistema": identificador = replace(identificador, candidato=replace(identificador.candidato, sistema="otro-sistema"))
    elif desajuste == "mecanismo": identificador = replace(identificador, candidato=replace(identificador.candidato, mecanismo="otro.campo"))
    elif desajuste == "revision": identificador = replace(identificador, contrato=replace(identificador.contrato, revision="f" * 64))
    elif desajuste == "version": identificador = replace(identificador, contrato=replace(identificador.contrato, version=99))
    _edicion_sin_confirmacion(tmp_path / "estado.json", replace(a, identificador_origen=identificador), politica_sintetica)


def test_contrato_deshabilitado_no_confirma_en_archivo_nuevo(tmp_path, contrato_sintetico, actuacion_ficticia):
    politica = PoliticaConfianza(CatalogoContratosRevisados((contrato_sintetico,)))
    _edicion_sin_confirmacion(tmp_path / "estado.json", actuacion_ficticia(id_origen="FICTICIO-A"), politica)


def test_candidato_no_se_eleva_aunque_exista_contrato_habilitado(tmp_path, actuacion_ficticia, politica_sintetica):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    m = MonitorActuaciones(tmp_path / "estado.json", politica_confianza=politica_sintetica)
    m.reconciliar("CASO_FICTICIO", [a])
    b = replace(a, identificador_origen=a.identificador_origen.candidato, descripcion="EDICIÓN FICTICIA")
    resultado = m.reconciliar("CASO_FICTICIO", [b])
    assert resultado.eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO


def test_persistencia_guarda_referencia_y_alcance_no_catalogo(tmp_path, actuacion_ficticia, politica_sintetica, contrato_sintetico):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta, politica_confianza=politica_sintetica).reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["state_revision"] == 2
    registro = datos["cases"]["CASO_FICTICIO"]["records"][0]
    assert registro["contract_ref"] == asdict(contrato_sintetico.referencia)
    assert registro["origin_scope"] == {"instancia": "local", "caso": "CASO_FICTICIO"}
    assert contrato_sintetico.evidencia.documento not in ruta.read_text(encoding="utf-8")


@pytest.mark.parametrize("politica_actual", ["ausente", "deshabilitada", "incompatible"])
def test_estado_no_introduce_confianza_sin_contrato_vigente(tmp_path, actuacion_ficticia, politica_sintetica, contrato_sintetico, politica_actual):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta, politica_confianza=politica_sintetica).reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    anterior = ruta.read_bytes()
    if politica_actual == "ausente": politica = PoliticaConfianza()
    elif politica_actual == "deshabilitada": politica = PoliticaConfianza(CatalogoContratosRevisados((contrato_sintetico,)))
    else:
        nuevo = replace(contrato_sintetico, version=2)
        politica = PoliticaConfianza(CatalogoContratosRevisados((nuevo,)), (nuevo.referencia,))
    with pytest.raises(TransicionRequerida): MonitorActuaciones(ruta, politica_confianza=politica)
    assert ruta.read_bytes() == anterior


def test_estado_falsifica_firma_pero_no_puede_aportar_catalogo(tmp_path, actuacion_ficticia, politica_sintetica):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta, politica_confianza=politica_sintetica).reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["trust_policy"] = PoliticaConfianza().firma("local")
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    anterior = ruta.read_bytes()
    with pytest.raises(TransicionRequerida): MonitorActuaciones(ruta)
    assert ruta.read_bytes() == anterior


def test_catalogo_en_payload_persistido_se_rechaza(tmp_path):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta).reconciliar("CASO_FICTICIO", [])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["catalogo_revisado"] = True
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    anterior = ruta.read_bytes()
    with pytest.raises(EstadoInvalido): MonitorActuaciones(ruta)
    assert ruta.read_bytes() == anterior


def test_estado_no_puede_declarar_modificacion_sin_identidad(tmp_path, actuacion_ficticia):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta).reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["cases"]["CASO_FICTICIO"]["records"][0]["status"] = EstadoReconciliacion.MODIFICADA.value
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    anterior = ruta.read_bytes()
    with pytest.raises(EstadoInvalido): MonitorActuaciones(ruta)
    assert ruta.read_bytes() == anterior


def test_retirar_contrato_durante_ejecucion_exige_transicion(tmp_path, actuacion_ficticia, politica_sintetica):
    ruta = tmp_path / "estado.json"
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    m = MonitorActuaciones(ruta, politica_confianza=politica_sintetica)
    m.reconciliar("CASO_FICTICIO", [a])
    anterior = ruta.read_bytes()
    m.politica_confianza = PoliticaConfianza()
    with pytest.raises(TransicionRequerida): m.reconciliar("CASO_FICTICIO", [replace(a, descripcion="EDICIÓN FICTICIA")])
    assert ruta.read_bytes() == anterior


def test_alcance_persistido_no_se_puede_cambiar(tmp_path, actuacion_ficticia, politica_sintetica):
    ruta = tmp_path / "estado.json"
    MonitorActuaciones(ruta, politica_confianza=politica_sintetica).reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["cases"]["CASO_FICTICIO"]["records"][0]["origin_scope"]["instancia"] = "otra-instancia"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(TransicionRequerida): MonitorActuaciones(ruta, politica_confianza=politica_sintetica)


def _convertir_a_revision_anterior(datos):
    resultado = deepcopy(datos)
    del resultado["state_revision"]
    del resultado["trust_policy"]
    for caso in resultado["cases"].values():
        for registro in caso["records"]:
            del registro["contract_ref"]
            del registro["origin_scope"]
    return resultado


@pytest.mark.parametrize("anterior", [True, False])
def test_transicion_explicita_no_eleva_ids_ni_genera_avisos_masivos(tmp_path, actuacion_ficticia, politica_sintetica, anterior):
    origen, destino = tmp_path / "antes.json", tmp_path / "despues.json"
    datos_observados = [actuacion_ficticia(id_origen=f"FICTICIO-{i}") for i in range(12)]
    MonitorActuaciones(origen, politica_confianza=politica_sintetica).reconciliar("CASO_FICTICIO", datos_observados)
    if anterior:
        datos = _convertir_a_revision_anterior(json.loads(origen.read_text(encoding="utf-8")))
        origen.write_text(json.dumps(datos), encoding="utf-8")
    contenido = origen.read_bytes()
    with pytest.raises(TransicionRequerida): MonitorActuaciones(origen)
    with pytest.warns(UserWarning, match="omitirse"):
        m = MonitorActuaciones.transicionar_estado(origen, destino)
    assert origen.read_bytes() == contenido
    assert m.estado["cases"] == {}
    resultado = m.reconciliar("CASO_FICTICIO", datos_observados)
    assert not resultado.eventos and len(resultado.actuaciones) == 12
    assert len({r.identidad_local for r in resultado.actuaciones}) == 12
    assert all(r["source_id"] is None for r in m.estado["cases"]["CASO_FICTICIO"]["records"])
    assert not MonitorActuaciones(destino).reconciliar("CASO_FICTICIO", datos_observados).eventos
    assert origen.read_bytes() == contenido


def test_transicion_no_sobrescribe_original_o_destino(tmp_path, actuacion_ficticia):
    origen, destino = tmp_path / "antes.json", tmp_path / "despues.json"
    MonitorActuaciones(origen).reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    contenido = origen.read_bytes()
    destino.write_text("PREEXISTENTE FICTICIO", encoding="utf-8")
    with pytest.raises(ValueError): MonitorActuaciones.transicionar_estado(origen, origen)
    with pytest.raises(FileExistsError): MonitorActuaciones.transicionar_estado(origen, destino)
    assert origen.read_bytes() == contenido
    assert destino.read_text(encoding="utf-8") == "PREEXISTENTE FICTICIO"


def test_fallo_transicion_no_destruye_original(tmp_path, actuacion_ficticia, monkeypatch):
    origen, destino = tmp_path / "antes.json", tmp_path / "despues.json"
    MonitorActuaciones(origen).reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    contenido = origen.read_bytes()
    def fallar(*args): raise OSError("Fallo de escritura simulado")
    monkeypatch.setattr("tinotify.persistence.monitor.os.fsync", fallar)
    with pytest.raises(OSError): MonitorActuaciones.transicionar_estado(origen, destino)
    assert origen.read_bytes() == contenido and not destino.exists()


@pytest.mark.parametrize("revision", [True, 99, "2"])
def test_revision_desconocida_no_se_transiciona(tmp_path, actuacion_ficticia, revision):
    origen, destino = tmp_path / "antes.json", tmp_path / "despues.json"
    MonitorActuaciones(origen).reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    datos = json.loads(origen.read_text(encoding="utf-8"))
    datos["state_revision"] = revision
    origen.write_text(json.dumps(datos), encoding="utf-8")
    contenido = origen.read_bytes()
    with pytest.raises(EstadoInvalido): MonitorActuaciones.transicionar_estado(origen, destino)
    assert origen.read_bytes() == contenido and not destino.exists()


def test_mismo_id_en_casos_distintos_no_comparte_identidad(tmp_path, actuacion_ficticia, politica_sintetica):
    m = MonitorActuaciones(tmp_path / "estado.json", politica_confianza=politica_sintetica)
    ids = []
    for caso in ("CASO_FICTICIO_A", "CASO_FICTICIO_B"):
        a = actuacion_ficticia(id_origen="FICTICIO-A", caso_origen=caso)
        r = m.reconciliar(caso, [a])
        ids.append(r.actuaciones[0].identidad_local)
        assert m.reconciliar(caso, [replace(a, descripcion="EDICIÓN FICTICIA")]).eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA
    assert ids[0] != ids[1]


def test_cambio_entre_contratos_no_fabrica_edicion(tmp_path, actuacion_ficticia, contrato_sintetico):
    segundo = replace(contrato_sintetico, clave="otro-contrato-pruebas", mecanismo="otro.campo")
    politica = PoliticaConfianza(CatalogoContratosRevisados((contrato_sintetico, segundo)), (contrato_sintetico.referencia, segundo.referencia))
    contexto = ContextoOrigen("local", "CASO_FICTICIO")
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    b = replace(a, identificador_origen=politica.verificar(IdentificadorCandidato("FICTICIO-A", segundo.sistema, segundo.mecanismo), segundo.referencia, contexto))
    m = MonitorActuaciones(tmp_path / "estado.json", politica_confianza=politica)
    m.reconciliar("CASO_FICTICIO", [a])
    assert m.reconciliar("CASO_FICTICIO", [b]).eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO


def test_motor_puro_rechaza_registro_sin_referencia(contrato_sintetico, actuacion_ficticia, politica_sintetica):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    estado, _ = reconciliar(None, [a], caso="CASO_FICTICIO", politica_confianza=politica_sintetica)
    del estado["records"][0]["contract_ref"]
    with pytest.raises(ContratoNoConfiable):
        reconciliar(estado, [replace(a, descripcion="EDICIÓN FICTICIA")], caso="CASO_FICTICIO", politica_confianza=politica_sintetica)


def test_secuencias_ambiguas_y_duplicados_siguen_sin_avisos_repetidos(tmp_path, actuacion_ficticia):
    a = actuacion_ficticia(identificador_origen=IdentificadorSigac("SIGAC-FICTICIO-A"))
    b = replace(a, descripcion="EDICIÓN FICTICIA")
    m = MonitorActuaciones(tmp_path / "estado.json")
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos
    assert m.reconciliar("CASO_FICTICIO", [b]).eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    for datos in ([b], [a], [b], [a]): assert not m.reconciliar("CASO_FICTICIO", datos).eventos
    otro = MonitorActuaciones(tmp_path / "duplicados.json")
    assert not otro.reconciliar("CASO_FICTICIO", [a, a]).eventos
    assert not otro.reconciliar("CASO_FICTICIO", [a]).eventos
    assert not otro.reconciliar("CASO_FICTICIO", [a, a]).eventos
