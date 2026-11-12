from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
from itertools import permutations

import pytest

from tinotify.domain.actuaciones import EstadoReconciliacion, TipoCambio
from tinotify.domain.notificaciones import Prioridad
from tinotify.domain.notificaciones import crear_notificacion
from tinotify.persistence.monitor import MonitorActuaciones
from tinotify.services.reconciliacion import reconciliar


def test_duplicados_tienen_identidades_locales_distintas(tmp_path, actuacion_ficticia, monitor_ficticio):
    monitor = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia()
    resultado = monitor.reconciliar("CASO_FICTICIO", [a, a])
    assert not resultado.eventos
    assert len(resultado.actuaciones) == 2
    ids = {r.identidad_local for r in resultado.actuaciones}
    assert len(ids) == 2
    assert all(r.estado == EstadoReconciliacion.LINEA_BASE for r in resultado.actuaciones)
    repetida = monitor.reconciliar("CASO_FICTICIO", [a, a])
    assert not repetida.eventos
    assert {r.identidad_local for r in repetida.actuaciones} == ids


def test_aumento_multiplicidad_conserva_cada_evento_y_agrupa_avisos(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia()
    original = m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [a, a, a])
    assert len(resultado.actuaciones) == 3
    assert len(resultado.eventos) == 2
    assert all(e.tipo == TipoCambio.PRIMERA_OBSERVACION for e in resultado.eventos)
    assert original.actuaciones[0].identidad_local in {r.identidad_local for r in resultado.actuaciones}
    assert len(m.notificaciones("CASO_FICTICIO", resultado)) == 1
    assert m.sincronizar("CASO_FICTICIO", [a, a, a]) == []
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos
    assert not m.reconciliar("CASO_FICTICIO", [a, a, a]).eventos


@pytest.mark.parametrize("posicion", [0, 1, 2])
def test_insercion_en_cualquier_posicion(tmp_path, actuacion_ficticia, posicion, monitor_ficticio):
    a = actuacion_ficticia(descripcion="A FICTICIA")
    b = actuacion_ficticia(descripcion="B FICTICIA", fecha=datetime(2019, 1, 1))
    c = actuacion_ficticia(descripcion="C FICTICIA")
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", [a, c])
    actuales = [a, c]
    actuales.insert(posicion, b)
    resultado = m.reconciliar("CASO_FICTICIO", actuales)
    assert len(resultado.eventos) == 1
    assert resultado.eventos[0].tipo == TipoCambio.PRIMERA_OBSERVACION


def test_todas_las_reordenaciones_son_invariantes(tmp_path, actuacion_ficticia, monitor_ficticio):
    datos = [actuacion_ficticia(descripcion=x) for x in ("A FICTICIA", "B FICTICIA", "C FICTICIA")]
    m = monitor_ficticio(tmp_path / "estado.json")
    inicial = m.reconciliar("CASO_FICTICIO", datos)
    ids = {r.identidad_local for r in inicial.actuaciones}
    for orden in permutations(datos):
        resultado = m.reconciliar("CASO_FICTICIO", list(orden))
        assert not resultado.eventos
        assert {r.identidad_local for r in resultado.actuaciones} == ids


CAMBIOS = [
    ("descripcion", "OTRA DESCRIPCIÓN FICTICIA"), ("remitente", "OTRO REMITENTE FICTICIO"),
    ("etapa", "OTRA ETAPA FICTICIA"), ("fecha", datetime(2020, 2, 1)),
    ("origen", "DIRECCION"), ("destino", "ASESOR"),
]


@pytest.mark.parametrize("campo,valor", CAMBIOS)
def test_edicion_con_identidad_estable_es_modificacion(tmp_path, actuacion_ficticia, campo, valor, monitor_ficticio):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    b = replace(a, **{campo: valor})
    m = monitor_ficticio(tmp_path / "estado.json")
    inicial = m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [b])
    assert resultado.actuaciones[0].identidad_local == inicial.actuaciones[0].identidad_local
    assert resultado.actuaciones[0].estado == EstadoReconciliacion.MODIFICADA
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.MODIFICACION_CONFIRMADA]
    assert not m.reconciliar("CASO_FICTICIO", [b]).eventos
    # Volver a una versión anterior con ID estable es otra edición observable.
    assert m.reconciliar("CASO_FICTICIO", [a]).eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA


@pytest.mark.parametrize("campo,valor", CAMBIOS)
def test_edicion_sin_id_es_ambigua_sin_unir_registros(tmp_path, actuacion_ficticia, campo, valor, monitor_ficticio):
    a = actuacion_ficticia()
    b = replace(a, **{campo: valor})
    m = monitor_ficticio(tmp_path / "estado.json")
    inicial = m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [b])
    assert resultado.actuaciones[0].identidad_local != inicial.actuaciones[0].identidad_local
    assert resultado.actuaciones[0].estado == EstadoReconciliacion.AMBIGUA
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.CAMBIO_AMBIGUO]
    assert len(m.estado["cases"]["CASO_FICTICIO"]["records"]) == 2
    repetida = m.reconciliar("CASO_FICTICIO", [b])
    assert not repetida.eventos
    assert repetida.actuaciones[0].estado == EstadoReconciliacion.AMBIGUA
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos


@pytest.mark.parametrize("estable", [False, True])
@pytest.mark.parametrize("cambio", ["agregar", "eliminar", "modificar", "duplicar"])
def test_cambios_de_anexos_se_reconcilian(tmp_path, actuacion_ficticia, anexo_ficticio, estable, cambio, monitor_ficticio):
    a = actuacion_ficticia(id_origen="FICTICIO-A" if estable else None, anexos=(anexo_ficticio,))
    anexos = {
        "agregar": (anexo_ficticio, replace(anexo_ficticio, archivo="segundo_ficticio.txt")),
        "eliminar": (), "modificar": (replace(anexo_ficticio, descripcion="OTRO ANEXO FICTICIO"),),
        "duplicar": (anexo_ficticio, anexo_ficticio),
    }[cambio]
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [replace(a, anexos=anexos)])
    esperado = TipoCambio.MODIFICACION_CONFIRMADA if estable else TipoCambio.CAMBIO_AMBIGUO
    assert [e.tipo for e in resultado.eventos] == [esperado]


def test_anexos_reordenados_no_producen_eventos(tmp_path, actuacion_ficticia, anexo_ficticio, monitor_ficticio):
    a = actuacion_ficticia(anexos=(anexo_ficticio, replace(anexo_ficticio, archivo="segundo_ficticio.txt")))
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", [a])
    assert not m.reconciliar("CASO_FICTICIO", [replace(a, anexos=tuple(reversed(a.anexos)))]).eventos


def test_igual_triple_con_remitente_distinto_no_colapsa(tmp_path, actuacion_ficticia, monitor_ficticio):
    a = actuacion_ficticia()
    b = replace(a, remitente="OTRO REMITENTE FICTICIO")
    m = monitor_ficticio(tmp_path / "estado.json")
    resultado = m.reconciliar("CASO_FICTICIO", [a, b])
    assert len({r.huella_version for r in resultado.actuaciones}) == 2
    assert len({r.identidad_local for r in resultado.actuaciones}) == 2


def test_historial_parcial_no_elimina_ni_repite_avisos(tmp_path, actuacion_ficticia, monitor_ficticio):
    a = actuacion_ficticia(descripcion="A FICTICIA")
    b = actuacion_ficticia(descripcion="B FICTICIA")
    c = actuacion_ficticia(descripcion="C FICTICIA")
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", [a, b])
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos
    assert not m.reconciliar("CASO_FICTICIO", []).eventos
    assert len(m.estado["cases"]["CASO_FICTICIO"]["records"]) == 2
    # B sigue ausente: C podría ser una edición, por lo que no se confirma alta.
    assert m.reconciliar("CASO_FICTICIO", [a, c]).eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    assert not m.reconciliar("CASO_FICTICIO", [a, b, c]).eventos


def test_id_que_aparece_no_se_fusiona_con_anonima(tmp_path, actuacion_ficticia, monitor_ficticio):
    a = actuacion_ficticia()
    m = monitor_ficticio(tmp_path / "estado.json")
    inicial = m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    assert resultado.eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    assert resultado.actuaciones[0].identidad_local != inicial.actuaciones[0].identidad_local


def test_perder_id_no_fabrica_correspondencia(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    assert m.reconciliar("CASO_FICTICIO", [actuacion_ficticia()]).eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO


def test_ids_diferentes_con_mismo_contenido_no_colapsan(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    b = actuacion_ficticia(id_origen="FICTICIO-B")
    m.reconciliar("CASO_FICTICIO", [a])
    resultado = m.reconciliar("CASO_FICTICIO", [b, a])
    assert len({r.identidad_local for r in resultado.actuaciones}) == 2
    assert resultado.eventos[0].tipo == TipoCambio.PRIMERA_OBSERVACION


def test_id_repetido_rechaza_consulta_sin_modificar_estado(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    m.reconciliar("CASO_FICTICIO", [a])
    original = ruta.read_bytes()
    with pytest.raises(ValueError):
        m.reconciliar("CASO_FICTICIO", [a, replace(a, descripcion="OTRA FICTICIA")])
    assert ruta.read_bytes() == original
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos


def test_identificadores_contextualizados_por_caso(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    primero = m.reconciliar("CASO_FICTICIO_A", [a])
    segundo = m.reconciliar("CASO_FICTICIO_B", [a])
    assert not primero.eventos and not segundo.eventos
    assert primero.actuaciones[0].identidad_local != segundo.actuaciones[0].identidad_local


def test_un_solo_motor_no_consulta_huella_legacy(tmp_path, actuacion_ficticia, monkeypatch, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    def no_legacy(*args):
        raise AssertionError("El motor legacy no debe usarse")
    monkeypatch.setattr(m, "identificar_actuacion", no_legacy)
    assert m.sincronizar("CASO_FICTICIO", [actuacion_ficticia()]) == []
    assert m.sincronizar("CASO_FICTICIO", [actuacion_ficticia()]) == []


@pytest.mark.parametrize("origen,prioridad", [("ASESOR", Prioridad.ALTA), ("DIRECCION", Prioridad.ALTA), ("OTRO", Prioridad.NORMAL)])
def test_avisos_ambiguos_genericos_con_prioridad_conocida(tmp_path, actuacion_ficticia, origen, prioridad, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia(origen=origen)
    m.sincronizar("CASO_FICTICIO_SECRETO", [a])
    aviso = m.sincronizar("CASO_FICTICIO_SECRETO", [replace(a, descripcion="OTRA FICTICIA")])[0]
    assert aviso.tipo == TipoCambio.CAMBIO_AMBIGUO
    assert aviso.prioridad == prioridad
    payload = str(asdict(aviso))
    assert "CASO_FICTICIO_SECRETO" not in payload
    assert a.remitente not in payload and "OTRA FICTICIA" not in payload
    assert "nueva actuación" not in aviso.titulo.lower()


def test_eventos_confirmados_y_avisos_distintos(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    b = actuacion_ficticia(id_origen="FICTICIO-B", origen="OTRO")
    m.sincronizar("CASO_FICTICIO", [a])
    avisos = m.sincronizar("CASO_FICTICIO", [replace(a, descripcion="EDITADA FICTICIA"), b])
    assert {n.tipo for n in avisos} == {TipoCambio.MODIFICACION_CONFIRMADA, TipoCambio.PRIMERA_OBSERVACION}
    assert {n.prioridad for n in avisos} == {Prioridad.NORMAL, Prioridad.ALTA}


def test_reemplazos_observacionalmente_identicos_son_indistinguibles(tmp_path, actuacion_ficticia, monitor_ficticio):
    m = monitor_ficticio(tmp_path / "estado.json")
    a = actuacion_ficticia()
    m.reconciliar("CASO_FICTICIO", [a])
    assert not m.reconciliar("CASO_FICTICIO", [replace(a)]).eventos


def test_motor_no_muta_estado_entrada(actuacion_ficticia, politica_sintetica):
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    estado, _ = reconciliar(None, [a], caso="CASO_FICTICIO", politica_confianza=politica_sintetica)
    anterior = deepcopy(estado)
    siguiente, resultado = reconciliar(estado, [replace(a, descripcion="EDICIÓN FICTICIA")], caso="CASO_FICTICIO", politica_confianza=politica_sintetica)
    assert estado == anterior and siguiente != estado
    assert resultado.eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA


def test_no_resuelve_heuristicamente_varios_candidatos(tmp_path, actuacion_ficticia, monitor_ficticio):
    datos = [actuacion_ficticia(descripcion=x) for x in ("A FICTICIA", "B FICTICIA", "C FICTICIA", "D FICTICIA")]
    m = monitor_ficticio(tmp_path / "estado.json")
    m.reconciliar("CASO_FICTICIO", datos[:2])
    resultado = m.reconciliar("CASO_FICTICIO", [datos[0], datos[2], datos[3]])
    assert len(resultado.eventos) == 2
    assert all(e.tipo == TipoCambio.CAMBIO_AMBIGUO for e in resultado.eventos)
    assert len(m.estado["cases"]["CASO_FICTICIO"]["records"]) == 4


@pytest.mark.parametrize("tipo", list(TipoCambio))
def test_payload_no_contiene_contexto_del_expediente(tipo):
    aviso = crear_notificacion("CASO_FICTICIO_PRIVADO", "ASESOR-->ESTUDIANTE", tipo)
    payload = asdict(aviso)
    assert set(payload) == {"tipo", "prioridad", "titulo", "mensaje"}
    assert "CASO_FICTICIO_PRIVADO" not in str(payload)
    assert "ASESOR" not in str(payload) and "ESTUDIANTE" not in str(payload)


def test_tipo_de_aviso_desconocido_se_rechaza():
    with pytest.raises(ValueError): crear_notificacion("CASO_FICTICIO", "OTRO", "desconocido")
