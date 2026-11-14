"""Pruebas sin PostgreSQL: contrato, codec, TLS y cierre por defecto."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tinotify.persistence.codec_postgres import a_filas, binario, de_filas
from tinotify.persistence.interfaces import Principal
from tinotify.persistence.postgres import AlmacenPostgres, ConfiguracionPostgres, crear_pool
from tinotify.services.reconciliacion import reconciliar


@pytest.mark.parametrize("clave", ["FICTICIO", "FICTICIO\x00", "FICTICIO\ud800", "a"*512])
def test_codec_utf8_no_pierde_claves(clave):
    assert binario(clave).decode("utf-8", "surrogatepass") == clave


def test_codec_rechaza_limite_sin_truncar():
    with pytest.raises(ValueError):
        binario("a"*513)


@pytest.mark.parametrize("identificado", [False, True])
def test_codec_registros_v22_conserva_orden_y_duplicados(actuacion_ficticia, politica_sintetica, identificado):
    a = actuacion_ficticia("ID_FICTICIO" if identificado else None)
    caso, _ = reconciliar(None, [a] if identificado else [a,a], caso="CASO_FICTICIO", politica_confianza=politica_sintetica)
    assert de_filas(a_filas(caso["records"])) == caso


@pytest.mark.parametrize("usuario", ["postgres", "postgres.proyecto", "service_role", "supabase_admin"])
def test_configuracion_rechaza_identidades_administrativas(tmp_path, usuario):
    ca = tmp_path/"ca.pem"
    ca.write_text("CERTIFICADO FICTICIO", encoding="utf-8")
    config = ConfiguracionPostgres(f"host=localhost user={usuario}",ca)
    with pytest.raises(ValueError):
        config.opciones()


@pytest.mark.parametrize("opcion", ["sslmode=disable", "sslmode=require", "port=6543", "options=-csearch_path=public"])
def test_configuracion_impide_degradar_tls_o_pooler(tmp_path, opcion):
    ca = tmp_path/"ca.pem"
    ca.write_text("CERTIFICADO FICTICIO", encoding="utf-8")
    with pytest.raises(ValueError):
        ConfiguracionPostgres(f"host=localhost user=login_ficticio {opcion}",ca).opciones()


def test_pool_no_conecta_al_crearlo_y_oculta_dsn(tmp_path):
    ca = tmp_path/"ca.pem"
    ca.write_text("CERTIFICADO FICTICIO", encoding="utf-8")
    config = ConfiguracionPostgres("host=localhost user=login_ficticio password=NO_ES_UN_SECRETO_REAL",ca)
    assert "NO_ES_UN_SECRETO_REAL" not in repr(config)
    pool = crear_pool(config)
    assert pool.closed
    assert config.opciones()["sslmode"] == "verify-full"


@pytest.mark.parametrize("sujeto,vence", [
    ("uuid_del_cliente", datetime.now(timezone.utc)+timedelta(hours=1)),
    (uuid4(), datetime(2020,1,1)),
    (uuid4(), datetime(2020,1,1,tzinfo=timezone.utc)),
])
def test_principal_no_acepta_identidad_o_vigencia_invalida(sujeto, vence):
    with pytest.raises(PermissionError):
        Principal(sujeto,vence).comprobar()


def test_sin_autenticador_no_hay_adaptador_activo():
    with pytest.raises(ValueError):
        AlmacenPostgres(None,None)
