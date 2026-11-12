from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tinotify.domain.actuaciones import TipoCambio
from tinotify.persistence.monitor import EstadoAntiguo, EstadoInvalido, MonitorActuaciones


def test_estado_minimo_sin_textos_de_expedientes(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    a = actuacion_ficticia()
    m = monitor_ficticio(ruta)
    assert not ruta.exists()
    m.reconciliar("CASO_FICTICIO", [a, a])
    texto = ruta.read_text(encoding="utf-8")
    estado = json.loads(texto)
    assert estado["schema_version"] == 2
    assert estado["fingerprint_version"] == 1
    assert len(estado["cases"]["CASO_FICTICIO"]["records"]) == 2
    assert a.descripcion not in texto and a.remitente not in texto
    assert a.etapa not in texto and a.fecha.isoformat() not in texto
    # Los IDs de caso y los hashes siguen siendo datos sensibles, no anónimos.
    assert "CASO_FICTICIO" in texto


def test_reinicio_conserva_identidades_y_no_repite_ambiguedades(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    a = actuacion_ficticia()
    b = replace(a, descripcion="EDICIÓN FICTICIA")
    m = monitor_ficticio(ruta)
    primero = m.reconciliar("CASO_FICTICIO", [a, a])
    nuevo = monitor_ficticio(ruta)
    repetida = nuevo.reconciliar("CASO_FICTICIO", [a, a])
    assert {r.identidad_local for r in primero.actuaciones} == {r.identidad_local for r in repetida.actuaciones}
    assert not repetida.eventos
    assert nuevo.reconciliar("CASO_FICTICIO", [b]).eventos[0].tipo == TipoCambio.CAMBIO_AMBIGUO
    assert not monitor_ficticio(ruta).reconciliar("CASO_FICTICIO", [b]).eventos


def test_reinicio_id_estable_y_historial_parcial(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    m = monitor_ficticio(ruta)
    primero = m.reconciliar("CASO_FICTICIO", [a])
    assert not m.reconciliar("CASO_FICTICIO", []).eventos
    nuevo = monitor_ficticio(ruta)
    resultado = nuevo.reconciliar("CASO_FICTICIO", [replace(a, descripcion="EDICIÓN FICTICIA")])
    assert resultado.actuaciones[0].identidad_local == primero.actuaciones[0].identidad_local
    assert resultado.eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA


def test_consulta_identica_no_escribe_estado(tmp_path, actuacion_ficticia, monkeypatch, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    a = actuacion_ficticia()
    m.reconciliar("CASO_FICTICIO", [a])
    contenido = ruta.read_bytes()
    def no_escribir(*args):
        raise AssertionError("No debe escribir una consulta idéntica")
    monkeypatch.setattr(m, "_guardar_estado", no_escribir)
    assert not m.reconciliar("CASO_FICTICIO", [a]).eventos
    assert ruta.read_bytes() == contenido


def test_fallo_escritura_no_adelanta_estado_y_permita_reintento(tmp_path, actuacion_ficticia, monkeypatch, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    a = actuacion_ficticia(id_origen="FICTICIO-A")
    b = replace(a, descripcion="EDICIÓN FICTICIA")
    m.reconciliar("CASO_FICTICIO", [a])
    original = ruta.read_bytes()
    memoria = deepcopy(m.estado)
    def fallar(*args):
        raise OSError("Fallo de escritura simulado")
    with monkeypatch.context() as contexto:
        contexto.setattr("tinotify.persistence.monitor.os.replace", fallar)
        with pytest.raises(OSError):
            m.reconciliar("CASO_FICTICIO", [b])
    assert m.estado == memoria and ruta.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []
    assert m.reconciliar("CASO_FICTICIO", [b]).eventos[0].tipo == TipoCambio.MODIFICACION_CONFIRMADA


@pytest.mark.parametrize("contenido", [
    b"", b"{", b"[]", b"null", b"true", b'\xff',
    b'{"schema_version": 2, "schema_version": 2}',
    b'{"schema_version": NaN}', b'{"schema_version": Infinity}',
    b'{"CASO_FICTICIO": ["no-es-huella"]}',
])
def test_archivo_corrupto_no_se_destruye(tmp_path, contenido, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    ruta.write_bytes(contenido)
    with pytest.raises(EstadoInvalido):
        monitor_ficticio(ruta)
    assert ruta.read_bytes() == contenido


@pytest.mark.parametrize("alteracion", [
    "version", "algoritmo", "booleano_version", "campo_extra", "falta_casos", "casos_lista",
    "uuid", "uuid_repetido", "id_repetido", "huella", "estado", "registros", "campo_registro",
    "migracion_invalida", "origen_invalido", "caso_invalido",
])
def test_estado_v2_inconsistente_rechazado_sin_destruir(tmp_path, actuacion_ficticia, alteracion, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    m.reconciliar("CASO_FICTICIO", [actuacion_ficticia(id_origen="FICTICIO-A")])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    caso = datos["cases"]["CASO_FICTICIO"]
    registro = caso["records"][0]
    if alteracion == "version": datos["schema_version"] = 99
    elif alteracion == "algoritmo": datos["fingerprint_version"] = 99
    elif alteracion == "booleano_version": datos["schema_version"] = True
    elif alteracion == "campo_extra": datos["extra"] = "FICTICIO"
    elif alteracion == "falta_casos": del datos["cases"]
    elif alteracion == "casos_lista": datos["cases"] = []
    elif alteracion == "uuid": registro["local_id"] = "no-es-uuid"
    elif alteracion == "uuid_repetido": caso["records"].append(deepcopy(registro))
    elif alteracion == "id_repetido":
        copia = deepcopy(registro)
        copia["local_id"] = "00000000-0000-4000-8000-000000000001"
        caso["records"].append(copia)
    elif alteracion == "huella": registro["version_hash"] = "no-es-huella"
    elif alteracion == "estado": registro["status"] = "desconocido"
    elif alteracion == "registros": caso["records"] = {}
    elif alteracion == "campo_registro": registro["extra"] = "FICTICIO"
    elif alteracion == "migracion_invalida": datos["migrated_from_v1"] = 1
    elif alteracion == "origen_invalido": registro["source_id"] = "ID NO VÁLIDO"
    elif alteracion == "caso_invalido": datos["cases"][""] = datos["cases"].pop("CASO_FICTICIO")
    contenido = json.dumps(datos).encode("utf-8")
    ruta.write_bytes(contenido)
    with pytest.raises(EstadoInvalido): monitor_ficticio(ruta)
    assert ruta.read_bytes() == contenido


@pytest.mark.parametrize("vacio", [True, False])
def test_estado_v1_reconocido_sin_sobrescribir(tmp_path, vacio, monitor_ficticio):
    ruta = tmp_path / "antiguo.json"
    datos = {} if vacio else {"CASO_FICTICIO": ["0" * 64]}
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    original = ruta.read_bytes()
    with pytest.raises(EstadoAntiguo): monitor_ficticio(ruta)
    assert ruta.read_bytes() == original


def test_migracion_explicita_baseline_sin_reconstruir_ids(tmp_path, actuacion_ficticia, monitor_ficticio):
    origen, destino = tmp_path / "antiguo.json", tmp_path / "nuevo.v2.json"
    origen.write_text(json.dumps({"CASO_FICTICIO": ["0" * 64]}), encoding="utf-8")
    original = origen.read_bytes()
    with pytest.warns(UserWarning, match="omitirse"):
        m = monitor_ficticio.migrar_estado_v1(origen, destino)
    assert origen.read_bytes() == original
    assert m.estado["migrated_from_v1"] is True and m.estado["cases"] == {}
    a = actuacion_ficticia()
    resultado = m.reconciliar("CASO_FICTICIO", [a, a])
    assert not resultado.eventos and len(resultado.actuaciones) == 2
    assert monitor_ficticio(destino).sincronizar("CASO_FICTICIO", [a, a]) == []
    assert origen.read_bytes() == original


def test_migracion_no_sobrescribe_origen_o_destino(tmp_path, monitor_ficticio):
    origen, destino = tmp_path / "antiguo.json", tmp_path / "nuevo.v2.json"
    origen.write_text("{}", encoding="utf-8")
    destino.write_text("CONTENIDO FICTICIO PREEXISTENTE", encoding="utf-8")
    with pytest.raises(ValueError): monitor_ficticio.migrar_estado_v1(origen, origen)
    with pytest.raises(FileExistsError): monitor_ficticio.migrar_estado_v1(origen, destino)
    assert origen.read_text(encoding="utf-8") == "{}"
    assert destino.read_text(encoding="utf-8") == "CONTENIDO FICTICIO PREEXISTENTE"


def test_migracion_repetida_no_reinicia_seguimiento(tmp_path, actuacion_ficticia, monitor_ficticio):
    origen, destino = tmp_path / "antiguo.json", tmp_path / "nuevo.v2.json"
    origen.write_text("{}", encoding="utf-8")
    with pytest.warns(UserWarning): m = monitor_ficticio.migrar_estado_v1(origen, destino)
    m.reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    contenido = destino.read_bytes()
    with pytest.raises(FileExistsError): monitor_ficticio.migrar_estado_v1(origen, destino)
    assert destino.read_bytes() == contenido


def test_fallo_migracion_conserva_original(tmp_path, monkeypatch, monitor_ficticio):
    origen, destino = tmp_path / "antiguo.json", tmp_path / "nuevo.v2.json"
    origen.write_text("{}", encoding="utf-8")
    def fallar(*args): raise OSError("Fallo simulado")
    monkeypatch.setattr("tinotify.persistence.monitor.os.fsync", fallar)
    with pytest.raises(OSError): monitor_ficticio.migrar_estado_v1(origen, destino)
    assert origen.read_text(encoding="utf-8") == "{}"
    assert not destino.exists()


@pytest.mark.parametrize("contenido", ["{", '{"CASO_FICTICIO": ["invalido"]}'])
def test_migracion_rechaza_origen_corrupto(tmp_path, contenido, monitor_ficticio):
    origen, destino = tmp_path / "antiguo.json", tmp_path / "nuevo.v2.json"
    origen.write_text(contenido, encoding="utf-8")
    with pytest.raises(EstadoInvalido): monitor_ficticio.migrar_estado_v1(origen, destino)
    assert origen.read_text(encoding="utf-8") == contenido
    assert not destino.exists()


def test_v2_no_se_trata_como_v1(tmp_path, actuacion_ficticia, monitor_ficticio):
    origen, destino = tmp_path / "estado.json", tmp_path / "otro.json"
    monitor_ficticio(origen).reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    with pytest.raises(EstadoInvalido): monitor_ficticio.migrar_estado_v1(origen, destino)
    assert not destino.exists()


def test_lote_invalido_no_persiste_parcialmente(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    m.reconciliar("CASO_FICTICIO", [])
    contenido = ruta.read_bytes()
    with pytest.raises(ValueError):
        m.reconciliar("CASO_FICTICIO", [actuacion_ficticia(), {}])
    assert ruta.read_bytes() == contenido


@pytest.mark.parametrize("caso", [True, None, "", "  ", "CASO\nFICTICIO"])
def test_caso_invalido_no_crea_archivo(tmp_path, actuacion_ficticia, caso, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    with pytest.raises(ValueError): monitor_ficticio(ruta).reconciliar(caso, [actuacion_ficticia()])
    assert not ruta.exists()


@pytest.mark.parametrize("contenido", ["{", "{}", '{"schema_version":99}'])
def test_corrupcion_posterior_a_carga_no_se_pisa(tmp_path, actuacion_ficticia, contenido, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    a = actuacion_ficticia()
    m.reconciliar("CASO_FICTICIO", [a])
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(EstadoInvalido): m.reconciliar("CASO_FICTICIO", [replace(a, descripcion="OTRA FICTICIA")])
    assert ruta.read_text(encoding="utf-8") == contenido


def test_instancia_obsoleta_no_sobrescribe_cambios_ya_guardados(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    primero, segundo = monitor_ficticio(ruta), monitor_ficticio(ruta)
    primero.reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    contenido = ruta.read_bytes()
    with pytest.raises(EstadoInvalido): segundo.reconciliar("OTRO_CASO_FICTICIO", [])
    assert ruta.read_bytes() == contenido


def test_archivo_borrado_no_reinicia_linea_base_silenciosamente(tmp_path, actuacion_ficticia, monitor_ficticio):
    ruta = tmp_path / "estado.json"
    m = monitor_ficticio(ruta)
    m.reconciliar("CASO_FICTICIO", [actuacion_ficticia()])
    ruta.unlink()
    with pytest.raises(EstadoInvalido): m.reconciliar("CASO_FICTICIO", [])
    assert not ruta.exists()
