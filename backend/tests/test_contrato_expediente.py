"""Contrato de identidad de expediente: cerrado por defecto y limitado a continuidad OBSERVADA.

Todo es sintético. Los contratos de aquí viven en catálogos de PRUEBA; ninguno acredita una identidad
real ni toca `CATALOGO_PRODUCCION`.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from backend.tests.test_integridad_historial_sigac import USUARIO, CLAVE, bloque, cliente_sintetico, pagina
from tinotify.demo.novedades import ServicioNovedadesLocal
from tinotify.domain.identificadores import (
    CATALOGO_PRODUCCION, AlcanceExpediente, CatalogoContratosRevisados, ContratoExpediente, ContratoNoConfiable,
    CONTRATO_CASO_NRO_CONTINUIDAD, EstadoContrato, EvidenciaRevision, ExpedienteVerificado, PoliticaConfianza,
    compromiso_expediente,
)
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
from tinotify.services.comparacion_v1_sigac import ComparacionNoPosible, comparar_huellas, ejecutar_comparacion, leer_huellas_v1
from tinotify.services.consulta_real_local import (
    IdentidadExpedienteNoVerificada, consultar_caso_acreditado, exigir_identidad_expediente,
)
from tinotify.services.politica_real_local import politica_real_local
from tinotify.services.monitor_local import monitorear

RAIZ = Path(__file__).resolve().parents[1]
CLAVE_TEST = b"clave-de-prueba-0123456789abcdef"
EVIDENCIA = EvidenciaRevision("documento-ficticio", "a" * 64, "Solo para pruebas; no es una revisión real.")


def contrato(**cambios):
    datos = dict(clave="caso-nro-prueba", version=1, sistema="sigac", mecanismo="caso_nro_hidcaso",
                 alcance=AlcanceExpediente.CONTINUIDAD_OBSERVADA_EN_INSTANCIA,
                 garantias=("el numero senala el mismo historial en lecturas repetidas",),
                 no_garantiza=("unicidad_global", "ausencia_de_reutilizacion"), evidencia=EVIDENCIA,
                 expedientes_acreditados=(compromiso_expediente(CLAVE_TEST, "sigac-real", "caso-nro-prueba", 101),))
    datos.update(cambios)
    return ContratoExpediente(**datos)


def politica_de_prueba():
    c = contrato()
    return PoliticaConfianza(CatalogoContratosRevisados(expedientes=(c,)), expedientes_habilitados=(c.referencia,),
                             clave_acreditacion=CLAVE_TEST)


# --- Contrato y política ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cambios", [
    {"no_garantiza": ()}, {"no_garantiza": ("unicidad_global",)}, {"no_garantiza": ("ausencia_de_reutilizacion",)},
    {"garantias": ()}, {"garantias": ("unicidad_global",)}, {"garantias": ("ausencia_de_reutilizacion", "x")},
    {"alcance": "global"}, {"expedientes_acreditados": ()}, {"expedientes_acreditados": ("x",)}, {"version": 0}, {"evidencia": True}, {"clave": " "}, {"garantias": ["lista"]},
])
def test_el_contrato_rechaza_afirmaciones_globales_o_incompletas(cambios):
    with pytest.raises(ValueError):
        contrato(**cambios)


def test_produccion_no_tiene_contratos_de_expediente_ni_se_puede_habilitar_uno_ajeno():
    assert PoliticaConfianza().tiene_contrato_expediente is False
    assert CATALOGO_PRODUCCION.buscar_expediente(contrato().referencia) is None
    with pytest.raises(ContratoNoConfiable):
        PoliticaConfianza(expedientes_habilitados=(contrato().referencia,))
    with pytest.raises(ContratoNoConfiable):
        PoliticaConfianza().exigir_expediente(101, "sigac-real")
    assert PoliticaConfianza().estado_expediente(contrato().referencia) is EstadoContrato.NO_REVISADO


def test_catalogado_pero_no_habilitado_sigue_cerrado_y_un_booleano_no_habilita():
    c = contrato()
    politica = PoliticaConfianza(CatalogoContratosRevisados(expedientes=(c,)))
    assert politica.estado_expediente(c.referencia) is EstadoContrato.DESHABILITADO
    with pytest.raises(ContratoNoConfiable):
        politica.exigir_expediente(1, "sigac-real")
    with pytest.raises(ValueError):
        PoliticaConfianza(expedientes_habilitados=True)
    with pytest.raises(ValueError):
        CatalogoContratosRevisados(expedientes=("contrato",))


def test_habilitado_en_catalogo_de_prueba_verifica_solo_enteros_positivos():
    politica = politica_de_prueba()
    assert politica.tiene_contrato_expediente
    assert isinstance(politica.exigir_expediente(101, "sigac-real"), ExpedienteVerificado)
    for malo in (0, -1, True, "101", 1.0, None):
        with pytest.raises(ContratoNoConfiable):
            politica.exigir_expediente(malo, "sigac-real")


def test_la_firma_sin_contratos_de_expediente_no_cambia_y_con_ellos_si():
    esperado = hashlib.sha256(json.dumps({"policy_version": 1, "instancia": "sigac-real", "contratos": []},
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert PoliticaConfianza().firma("sigac-real") == esperado
    assert politica_de_prueba().firma("sigac-real") != esperado
    assert politica_de_prueba().firma("sigac-real") == politica_de_prueba().firma("sigac-real")


def test_cualquier_cambio_del_contrato_cambia_su_referencia():
    assert contrato().referencia != contrato(version=2).referencia
    assert contrato().referencia != contrato(garantias=("otra garantia",)).referencia


# --- Compuertas ------------------------------------------------------------------------------------------------------

def test_la_compuerta_exige_una_politica_explicita_y_un_contrato_habilitado():
    with pytest.raises(IdentidadExpedienteNoVerificada):
        exigir_identidad_expediente(None, 101)
    with pytest.raises(IdentidadExpedienteNoVerificada):
        exigir_identidad_expediente(PoliticaConfianza(), 101)
    assert exigir_identidad_expediente(politica_de_prueba(), 101).numero == 101


class EntradaFallida:
    llamadas = 0

    def __call__(self):
        EntradaFallida.llamadas += 1
        raise AssertionError("no debe autenticar")


def servicio_real(tmp_path, politica=None):
    return ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "real.sqlite3", politica=politica, perfil="real"),
                                  instancia="sigac-real")


def test_el_monitor_real_sigue_cerrado_con_el_catalogo_de_produccion(tmp_path):
    servicio = servicio_real(tmp_path)
    EntradaFallida.llamadas = 0
    with pytest.raises(IdentidadExpedienteNoVerificada):
        monitorear(object(), EntradaFallida(), total_casos=1, caso_numero=101, servicio=servicio)
    assert EntradaFallida.llamadas == 0


def test_el_monitor_real_no_acepta_posicion_ni_sin_seleccion_aunque_haya_contrato(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    for extra in ({"indice_caso": 1}, {}, {"indice_caso": 1, "caso_numero": 101}):
        with pytest.raises(IdentidadExpedienteNoVerificada):
            monitorear(object(), EntradaFallida(), total_casos=1, servicio=servicio, **extra)
    assert EntradaFallida.llamadas == 0


def test_el_monitor_real_sigue_deshabilitado_incluso_con_contrato_habilitado(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    with pytest.raises(IdentidadExpedienteNoVerificada, match="deshabilitado"):
        monitorear(object(), EntradaFallida(), total_casos=1, caso_numero=101, servicio=servicio)


def test_el_perfil_sintetico_exige_exactamente_una_seleccion(tmp_path):
    servicio = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    for extra in ({}, {"indice_caso": 1, "caso_numero": 5}, {"caso_numero": 0}, {"caso_numero": True}):
        with pytest.raises(ValueError):
            monitorear(object(), EntradaFallida(), total_casos=1, servicio=servicio, **extra)


def test_el_cli_usa_caso_numero_rechaza_posicion_y_permanece_bloqueado(monkeypatch, capsys, tmp_path):
    sys.path.insert(0, str(RAIZ / "scripts"))
    try:
        import sigac_local as cli
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "SigacClient", lambda: pytest.fail("No debe abrir el cliente"))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("No debe pedir confirmación"))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: pytest.fail("No debe pedir credenciales"))
    base = ["--db", str(tmp_path / "real.sqlite3")]
    for orden in ("consultar", "monitorear"):
        args = [*base, orden, "--autorizar-sigac-real", "--tipo", "T", "--total-casos", "3"]
        with pytest.raises(SystemExit) as salida:  # sin número de caso
            cli.main(args)
        assert salida.value.code == 2
        with pytest.raises(SystemExit) as salida:  # la posición ya no existe
            cli.main([*args, "--indice-caso", "1"])
        assert salida.value.code == 2
        with pytest.raises(SystemExit) as salida:
            cli.main([*args, "--caso-numero", "0"])
        assert salida.value.code == 2
        assert cli.main([*args, "--caso-numero", "101"]) == 4
        salida = capsys.readouterr().out
        assert "bloqueada" in salida or "deshabilitado" in salida
    assert not (tmp_path / "real.sqlite3").exists()


# --- Comparación con v1 ----------------------------------------------------------------------------------------------

def crear_v1(ruta, huellas, *, esquema="1", expedientes=1):
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE meta(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        CREATE TABLE expedientes(id TEXT PRIMARY KEY, estado_id TEXT, caso TEXT, generacion INTEGER, fencing INTEGER, incluido INTEGER);
        CREATE TABLE actuaciones(expediente_id TEXT NOT NULL, local_id TEXT NOT NULL, orden INTEGER NOT NULL,
            version_hash TEXT NOT NULL, status TEXT NOT NULL, source_id TEXT, contract_ref TEXT, origin_scope TEXT,
            PRIMARY KEY(expediente_id, local_id));""")
    con.executemany("INSERT INTO meta VALUES(?,?)", [("esquema", esquema), ("perfil", "real")])
    for n in range(expedientes):
        con.execute("INSERT INTO expedientes VALUES(?,?,?,?,?,?)", (f"e{n}", "s", f"c{n}", 1, 1, 1))
    for i, h in enumerate(huellas):
        con.execute("INSERT INTO actuaciones VALUES('e0',?,?,?,'linea_base',NULL,NULL,NULL)", (f"l{i}", i, h))
    con.commit()
    con.close()


def h(n):
    return hashlib.sha256(str(n).encode()).hexdigest()


def test_comparar_huellas_respeta_multiplicidades_y_solo_devuelve_conteos():
    previas = [h(1), h(1), h(2)]
    ok = comparar_huellas(previas, [h(2), h(1), h(1), h(3)])
    assert ok["veredicto"] == "continuidad_observada" and ok["v1_ausentes_en_lectura"] == 0
    assert ok["contenidas_con_multiplicidad"] == 3 and ok["adicionales_en_lectura"] == 1
    # Una copia de menos de una huella repetida NO está contenida aunque el conjunto de huellas coincida.
    corto = comparar_huellas(previas, [h(1), h(2)])
    assert corto["veredicto"] == "rechazada" and corto["v1_ausentes_en_lectura"] == 1
    assert comparar_huellas(previas, [h(9)])["veredicto"] == "rechazada"
    assert comparar_huellas([], [h(1)])["veredicto"] == "rechazada"
    assert all(isinstance(v, (int, bool, str)) for v in ok.values())
    assert not any(isinstance(v, str) and len(v) == 64 for v in ok.values())


def test_leer_huellas_v1_es_inmutable_y_valida_la_forma(tmp_path):
    ruta = tmp_path / "v1.sqlite3"
    crear_v1(ruta, [h(1), h(1), h(2)])
    antes = hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert leer_huellas_v1(ruta) == Counter({h(1): 2, h(2): 1})
    assert hashlib.sha256(ruta.read_bytes()).hexdigest() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["v1.sqlite3"]  # sin -wal/-shm/-journal
    for nombre, kwargs in (("v2", {"esquema": "2"}), ("dos", {"expedientes": 2})):
        otra = tmp_path / f"{nombre}.sqlite3"
        crear_v1(otra, [h(1)], **kwargs)
        with pytest.raises(ComparacionNoPosible):
            leer_huellas_v1(otra)
    vacia = tmp_path / "vacia.sqlite3"
    crear_v1(vacia, [])
    malo = tmp_path / "malo.sqlite3"
    crear_v1(malo, ["no-es-hex"])
    for ruta_mala in (vacia, malo, tmp_path / "inexistente.sqlite3", tmp_path / "x.txt"):
        with pytest.raises(ComparacionNoPosible):
            leer_huellas_v1(ruta_mala)


def test_ejecutar_comparacion_con_http_simulado_lee_una_vez_y_no_persiste(tmp_path):
    contenido = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(3)))
    with cliente_sintetico([contenido]) as (cliente, _):
        cliente.autenticar(USUARIO, CLAVE, tipo="2", total_casos_esperado=1)
        huellas = [a.huella_version for a in cliente.consultar_historial(101)]
    ruta = tmp_path / "v1.sqlite3"
    crear_v1(ruta, huellas)
    antes = hashlib.sha256(ruta.read_bytes()).hexdigest()
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        resumen = ejecutar_comparacion(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, ruta_v1=ruta)
        assert llamadas.count("casos.formCaso.con") == 1
    assert resumen["veredicto"] == "continuidad_observada" and resumen["contenidas_con_multiplicidad"] == 3
    assert resumen["persistencia"] == "ninguna" and resumen["v1_modificado"] is False
    assert hashlib.sha256(ruta.read_bytes()).hexdigest() == antes
    assert "CONTENIDO_SINTETICO" not in json.dumps(resumen)
    # Si falta una huella previa (o un caso no figura en el listado), se rechaza.
    crear_v1(tmp_path / "otra.sqlite3", [*huellas, h(99)])
    with cliente_sintetico([contenido]) as (cliente, _):
        r = ejecutar_comparacion(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101,
                                 ruta_v1=tmp_path / "otra.sqlite3")
    assert r["veredicto"] == "rechazada" and r["v1_ausentes_en_lectura"] == 1
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        r = ejecutar_comparacion(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=555, ruta_v1=ruta)
        assert "casos.formCaso.con" not in llamadas
    assert r["veredicto"] == "rechazada" and r["motivo"] == "caso_no_listado_o_repetido"


def test_el_script_de_comparacion_exige_bandera_y_terminal_antes_de_cualquier_conexion(monkeypatch, tmp_path):
    sys.path.insert(0, str(RAIZ / "scripts"))
    try:
        import comparar_v1_sigac as cli
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(cli, "SigacClient", lambda: pytest.fail("No debe abrir el cliente"))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: pytest.fail("No debe pedir credenciales"))
    comunes = ["--db", str(tmp_path / "v1.sqlite3"), "--tipo", "T", "--total-casos", "3", "--caso-numero", "101"]
    with pytest.raises(SystemExit) as salida:
        cli.main(comunes)
    assert salida.value.code == 2
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit) as salida:
        cli.main([*comunes, "--autorizar-sigac-real"])
    assert salida.value.code == 2
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert cli.main([*comunes, "--autorizar-sigac-real"]) == 1  # v1 inexistente: se detiene antes de pedir nada


# --- Acreditación de un expediente concreto y consulta manual ---------------------------------------------------------

def test_solo_el_numero_acreditado_pasa_y_los_demas_quedan_cerrados():
    politica = politica_de_prueba()
    assert politica.exigir_expediente(101, "sigac-real").numero == 101
    for otro in (1, 100, 102, 202, 99999):  # «los otros 14»: ninguno hereda el contrato
        with pytest.raises(ContratoNoConfiable):
            politica.exigir_expediente(otro, "sigac-real")
    with pytest.raises(ContratoNoConfiable):  # otra instancia
        politica.exigir_expediente(101, "otra-instancia")
    c = contrato()
    sin_clave = PoliticaConfianza(CatalogoContratosRevisados(expedientes=(c,)), expedientes_habilitados=(c.referencia,))
    with pytest.raises(ContratoNoConfiable):
        sin_clave.exigir_expediente(101, "sigac-real")
    otra_clave = PoliticaConfianza(CatalogoContratosRevisados(expedientes=(c,)), expedientes_habilitados=(c.referencia,),
                                   clave_acreditacion=b"otra-clave-de-prueba-0123456789")
    with pytest.raises(ContratoNoConfiable):
        otra_clave.exigir_expediente(101, "sigac-real")


def test_la_clave_de_acreditacion_no_cambia_la_firma_ni_concede_nada():
    c = contrato()
    catalogo = CatalogoContratosRevisados(expedientes=(c,))
    con_clave = PoliticaConfianza(catalogo, expedientes_habilitados=(c.referencia,), clave_acreditacion=CLAVE_TEST)
    sin_clave = PoliticaConfianza(catalogo, expedientes_habilitados=(c.referencia,))
    assert con_clave.firma("sigac-real") == sin_clave.firma("sigac-real")
    assert not PoliticaConfianza(catalogo, clave_acreditacion=CLAVE_TEST).tiene_contrato_expediente


def test_el_contrato_de_produccion_es_acotado_y_su_evidencia_coincide_con_el_documento():
    c = CONTRATO_CASO_NRO_CONTINUIDAD
    assert CATALOGO_PRODUCCION.buscar_expediente(c.referencia) is c
    assert not CATALOGO_PRODUCCION._referencias  # sin contratos de actuación
    assert {"unicidad_global", "ausencia_de_reutilizacion"} <= set(c.no_garantiza)
    assert len(c.expedientes_acreditados) == 1
    assert PoliticaConfianza().tiene_contrato_expediente is False  # catalogado, NO habilitado por defecto
    with pytest.raises(ContratoNoConfiable):
        PoliticaConfianza().exigir_expediente(101, "sigac-real")
    documento = RAIZ.parent / "docs" / "evidencia" / "comparacion-v1-sigac-continuidad.json"
    datos = json.loads(documento.read_text(encoding="utf-8"))
    canonico = json.dumps(datos, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(canonico.encode()).hexdigest() == c.evidencia.huella_documento
    assert datos["veredicto"] == "continuidad_observada" and datos["contenidas_con_multiplicidad"] == datos["huellas_v1"] == 709
    # Sanidad: ningún valor largo ni entero que parezca un número de expediente.
    assert not any(isinstance(v, str) and len(v) > 200 for v in datos.values())
    assert not any(isinstance(v, int) and not isinstance(v, bool) and 10_000 <= v < 10**9 for v in datos.values())


def test_politica_real_local_exige_la_clave_local(tmp_path):
    with pytest.raises(IdentidadExpedienteNoVerificada):
        politica_real_local(tmp_path / "no-existe.json")
    for nombre, contenido in (("malo", '{"version": 1, "clave_hex": "zz"}'), ("corto", '{"version": 1, "clave_hex": "00"}')):
        ruta = tmp_path / f"{nombre}.json"
        ruta.write_text(contenido, encoding="utf-8")
        with pytest.raises(IdentidadExpedienteNoVerificada):
            politica_real_local(ruta)
    bueno = tmp_path / "bueno.json"
    bueno.write_text(json.dumps({"version": 1, "clave_hex": CLAVE_TEST.hex()}), encoding="utf-8")
    politica = politica_real_local(bueno)
    assert politica.tiene_contrato_expediente
    with pytest.raises(ContratoNoConfiable):  # la clave de prueba no corresponde al compromiso de producción
        politica.exigir_expediente(101, "sigac-real")


def test_consulta_manual_real_con_http_simulado_es_linea_base_sin_novedades(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())
    contenido = pagina(*(bloque(f"CONTENIDO_SINTETICO_{n}") for n in range(4)))
    with cliente_sintetico([contenido]) as (cliente, llamadas):
        r1 = consultar_caso_acreditado(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio)
        assert llamadas.count("casos.formCaso.con") == 1
    assert r1["baseline"] is True and r1["novedades_nuevas"] == 0 and r1["actuaciones"] == 4 and r1["generacion"] == 1
    assert r1["notificaciones"] == "no_activadas" and r1["transferencia_externa"] == "no_autorizada" and "caso" not in r1
    assert "CONTENIDO_SINTETICO" not in json.dumps(r1)
    with cliente_sintetico([contenido]) as (cliente, _):
        r2 = consultar_caso_acreditado(cliente, USUARIO, CLAVE, tipo="2", total_casos=1, caso_numero=101, servicio=servicio)
    assert r2["baseline"] is False and r2["novedades_nuevas"] == 0 and r2["actuaciones"] == 4


def test_consulta_manual_real_no_conecta_si_no_esta_acreditado_o_el_perfil_no_es_real(tmp_path):
    servicio = servicio_real(tmp_path, politica_de_prueba())

    class SinRed:
        def __getattr__(self, nombre):
            pytest.fail("No debe autenticar ni conectar")
    with pytest.raises(IdentidadExpedienteNoVerificada):
        consultar_caso_acreditado(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=102, servicio=servicio)
    sintetico = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "s.sqlite3"))
    with pytest.raises(IdentidadExpedienteNoVerificada):
        consultar_caso_acreditado(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=101, servicio=sintetico)
    sin_habilitar = ServicioNovedadesLocal(AlmacenSqliteLocal(tmp_path / "r.sqlite3", perfil="real"), instancia="sigac-real")
    with pytest.raises(IdentidadExpedienteNoVerificada):
        consultar_caso_acreditado(SinRed(), "u", "c", tipo="2", total_casos=1, caso_numero=101, servicio=sin_habilitar)


def test_el_cli_consultar_real_se_detiene_sin_clave_valida_y_el_monitor_sigue_deshabilitado(monkeypatch, capsys, tmp_path):
    sys.path.insert(0, str(RAIZ / "scripts"))
    try:
        import sigac_local as cli
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "SigacClient", lambda: pytest.fail("No debe abrir el cliente"))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("No debe pedir confirmación"))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: pytest.fail("No debe pedir credenciales"))
    base = ["--db", str(tmp_path / "v2.sqlite3"), "consultar", "--autorizar-sigac-real", "--tipo", "2", "--total-casos", "15",
            "--caso-numero", "101"]
    assert cli.main([*base, "--acreditacion", str(tmp_path / "no-existe.json")]) == 4
    # Con una clave presente pero que no acredita el número, tampoco se conecta ni se crea el archivo v2.
    clave = tmp_path / "clave.json"
    clave.write_text(json.dumps({"version": 1, "clave_hex": CLAVE_TEST.hex()}), encoding="utf-8")
    assert cli.main([*base, "--acreditacion", str(clave)]) == 4
    assert not (tmp_path / "v2.sqlite3").exists()
    assert cli.main(["--db", str(tmp_path / "v2.sqlite3"), "monitorear", "--autorizar-sigac-real", "--tipo", "2",
                     "--total-casos", "15", "--caso-numero", "101"]) == 4
    assert "deshabilitado" in capsys.readouterr().out
