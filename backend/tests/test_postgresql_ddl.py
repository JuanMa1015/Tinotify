"""Guardas estáticas y contrato real v2.2; NO ejecutan ni emulan PostgreSQL."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import re

import pytest

from tinotify.domain.actuaciones import EstadoReconciliacion, TipoCambio, VERSION_HUELLA
from tinotify.domain.identificadores import (
    ReferenciaContrato, clave_estable, CatalogoContratosRevisados,
    ContextoOrigen, IdentificadorCandidato, PoliticaConfianza,
)
from tinotify.persistence.monitor import (
    MonitorActuaciones, REVISION_ESTADO, TransicionRequerida, _nuevo_estado, _validar_v2,
)
from tinotify.services.reconciliacion import reconciliar


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'supabase/migrations/20261112160000_crear_nucleo_reconciliacion.sql'
SQL = MIGRATION.read_text(encoding='utf-8')
CODE = re.sub(r'--[^\n]*', '', SQL)
TABLES = {
    'app.estudiantes', 'app.estados_reconciliacion', 'app.expedientes',
    'app.actuaciones', 'app.eventos', 'app_private.accesos_sigac',
    'app_private.sincronizaciones', 'app_private.importaciones',
}


def cuerpo(tabla):
    return re.search(r'CREATE TABLE ' + re.escape(tabla) + r' \((.*?)\n\);', CODE, re.S).group(1)


def test_solo_ocho_tablas_y_4a_inmutable():
    assert set(re.findall(r'CREATE TABLE ([a-z_.]+)', CODE)) == TABLES
    original = ROOT / 'supabase/migrations/20261112050000_preparar_esquemas_privados.sql'
    assert hashlib.sha256(original.read_bytes()).hexdigest() == '777b0b12b445a00eb31cd1c54931e35b0f31b8e6d8f81bb23dc9812982e2fba8'
    assert MIGRATION.name[:14] > original.name[:14]


@pytest.mark.parametrize('tabla', sorted(TABLES))
def test_cierre_estatico_de_cada_tabla(tabla):
    assert 'PRIMARY KEY' in cuerpo(tabla)
    assert f'ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;' in CODE
    assert f'ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;' in CODE
    cierre = re.search(r'REVOKE ALL PRIVILEGES ON TABLE ' + re.escape(tabla) + r'\s+FROM ([^;]+);', CODE).group(1)
    assert {r.strip() for r in cierre.split(',')} == {
        'PUBLIC', 'anon', 'authenticated', 'service_role',
        'tinotify_api', 'tinotify_sync', 'tinotify_notifications',
    }


def test_sin_habilitacion_operativa_o_elevacion():
    assert not re.search(r'\bGRANT\b', CODE)
    assert not re.search(r'CREATE\s+(?:OR REPLACE\s+)?(?:FUNCTION|PROCEDURE|POLICY|ROLE|SCHEMA)\b', CODE)
    assert not re.search(r'\bSET\s+(?:LOCAL\s+)?ROLE\b|\bOWNER TO\b|\bDISABLE ROW LEVEL', CODE)
    assert not re.search(r'^\s*(?:INSERT INTO|DELETE FROM|TRUNCATE|DROP)\b', CODE, re.M)
    assert "CURRENT_USER <> 'postgres'" in CODE
    assert 'a.grantee <> c.relowner' in CODE
    assert CODE.strip().startswith('BEGIN;') and CODE.strip().endswith('COMMIT;')


def test_identidad_estable_excluye_huella_y_no_depende_de_nulls():
    indice = re.search(r'CREATE UNIQUE INDEX una_identidad_estable_por_alcance(.*?);', CODE, re.S).group(1)
    for campo in ('estudiante_id','estado_id','expediente_id','contrato_clave_utf8',
                  'contrato_version_decimal','contrato_revision','source_id'):
        assert campo in indice
    assert 'version_hash' not in indice and 'orden_registro' not in indice
    assert 'WHERE source_id IS NOT NULL' in indice
    act = cuerpo('app.actuaciones')
    for campo in ('source_id','contrato_clave_utf8','contrato_version_decimal',
                  'contrato_revision','alcance_instancia_utf8','alcance_caso_utf8'):
        assert f'{campo} IS NULL' in act and f'{campo} IS NOT NULL' in act
    assert "source_id IS NOT NULL OR status <> 'modificada'" in act


def test_unicidad_nativa_de_cabecera_y_reserva():
    cabecera = re.search(r'CREATE UNIQUE INDEX una_cabecera_viva(.*?);', CODE, re.S).group(1)
    assert '(estudiante_id,instancia_utf8)' in cabecera
    assert "WHERE situacion IN ('activo','transicion_requerida')" in cabecera
    reserva = re.search(r'CREATE UNIQUE INDEX una_sincronizacion_activa(.*?);', CODE, re.S).group(1)
    assert '(estudiante_id,estado_id,expediente_id)' in reserva
    assert "WHERE estado IN ('reservada','ejecutando')" in reserva


@pytest.mark.parametrize('tabla', ['app.actuaciones','app.eventos','app_private.accesos_sigac','app_private.sincronizaciones'])
def test_fk_de_datos_incluyen_tenant_y_caso(tabla):
    claves = re.findall(r'FOREIGN KEY \(([^)]+)\)', cuerpo(tabla))
    assert claves
    for clave in claves:
        assert 'estudiante_id' in clave and 'estado_id' in clave
        if 'alcance_instancia_utf8' not in clave:
            assert 'expediente_id' in clave


def test_alcances_igualan_cabecera_y_caso_sin_ciclos():
    act = cuerpo('app.actuaciones')
    assert 'REFERENCES app.estados_reconciliacion(estudiante_id,id,instancia_utf8)' in act
    assert 'REFERENCES app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8)' in act
    assert 'UNIQUE (estudiante_id,estado_id,local_id)' in act
    assert 'CONSTRAINT actuaciones_orden_uq UNIQUE' in act
    assert act.count('DEFERRABLE INITIALLY DEFERRED') == 1
    assert 'versiones_actuacion' not in CODE and 'observaciones' not in CODE


def test_enumeraciones_coinciden_con_motor_real():
    status = re.search(r'status IN \((.*?)\)', cuerpo('app.actuaciones'), re.S).group(1)
    tipo = re.search(r'tipo IN \((.*?)\)', cuerpo('app.eventos'), re.S).group(1)
    assert set(re.findall(r"'([^']+)'", status)) == {e.value for e in EstadoReconciliacion}
    assert set(re.findall(r"'([^']+)'", tipo)) == {e.value for e in TipoCambio}
    assert f'state_revision = {REVISION_ESTADO}' in CODE
    assert f'fingerprint_version = {VERSION_HUELLA}' in CODE


@pytest.mark.parametrize('con_id', [False, True])
def test_columnas_cubren_records_producidos_por_motor(actuacion_ficticia, politica_sintetica, con_id):
    a = actuacion_ficticia('ID_FICTICIO' if con_id else None)
    caso, resultado = reconciliar(None, [a], caso='CASO_FICTICIO', politica_confianza=politica_sintetica)
    estado = _nuevo_estado(politica=politica_sintetica)
    estado['cases']['CASO_FICTICIO'] = caso
    _validar_v2(estado)
    assert resultado.eventos == ()
    registro = caso['records'][0]
    assert set(registro) == {'local_id','source_id','contract_ref','origin_scope','version_hash','status'}
    columnas = {'local_id','source_id','version_hash','status','contrato_clave_utf8',
                'contrato_version_decimal','contrato_revision','alcance_instancia_utf8','alcance_caso_utf8','orden_registro'}
    assert all(re.search(r'^\s+'+campo+r'\s', cuerpo('app.actuaciones'), re.M) for campo in columnas)
    if con_id:
        clave = clave_estable(a.identificador_origen)
        assert clave == ('contrato-pruebas', 1, a.identificador_origen.contrato.revision,
                         'local', 'CASO_FICTICIO', 'ID_FICTICIO')


def test_estructura_valida_no_introduce_confianza_desde_datos(actuacion_ficticia, politica_sintetica, tmp_path):
    caso, _ = reconciliar(None, [actuacion_ficticia('ID_FICTICIO')], caso='CASO_FICTICIO', politica_confianza=politica_sintetica)
    estado = _nuevo_estado()  # Política real vacía, sin evidencia sintética habilitada.
    estado['cases']['CASO_FICTICIO'] = deepcopy(caso)
    _validar_v2(estado)  # Forma válida no equivale a confianza.
    monitor = MonitorActuaciones(tmp_path / 'estado_ficticio_no_creado.json')
    with pytest.raises(TransicionRequerida):
        monitor._validar_activo(estado)
    assert not monitor.archivo_estado.exists()


@pytest.mark.parametrize('clave', ['CONTRATO_FICTICIO','CLAVE\x00FICTICIA','CLAVE\ud800FICTICIA'])
def test_codec_propuesto_preserva_claves_admitidas_sin_adaptador(clave):
    ReferenciaContrato(clave, 1, '0'*64)
    binario = clave.encode('utf-8', errors='surrogatepass')
    assert binario.decode('utf-8', errors='surrogatepass') == clave
    assert 'contrato_clave_utf8 bytea' in CODE


def test_cabecera_y_caso_vacio_siguen_siendo_distintos():
    vacio = _nuevo_estado()
    caso_vacio = deepcopy(vacio)
    caso_vacio['cases']['CASO_FICTICIO'] = {'records': []}
    _validar_v2(vacio)
    _validar_v2(caso_vacio)
    assert vacio != caso_vacio
    assert 'incluido_en_estado boolean NOT NULL DEFAULT false' in CODE


def test_pruebas_remotas_son_explicitas_y_no_autoejecutables():
    integridad = (ROOT/'supabase/tests/4b1_integridad.sql').read_text(encoding='utf-8')
    assert integridad.startswith('\\set ON_ERROR_STOP on')
    assert integridad.rstrip().endswith('ROLLBACK;')
    assert 'SQLSTATE esperado' in integridad
    assert not re.search(r'^\s*(?:TRUNCATE|DROP|CREATE FUNCTION|CREATE ROLE|GRANT)\b', integridad, re.M)
    assert 'supabase db push' not in integridad


def _verificar_ficticio(contrato, instancia='INSTANCIA_FICTICIA', caso='CASO_FICTICIO', source='ID_FICTICIO'):
    politica = PoliticaConfianza(CatalogoContratosRevisados((contrato,)), (contrato.referencia,))
    return politica.verificar(
        IdentificadorCandidato(source, contrato.sistema, contrato.mecanismo),
        contrato.referencia, ContextoOrigen(instancia, caso),
    )


def _proyeccion_formal(identidad, estudiante='ESTUDIANTE_FICTICIO', epoca='EPOCA_FICTICIA'):
    # Solo prueba algebraica. No ejecuta ni emula restricciones PostgreSQL.
    clave, version, revision, instancia, caso, source = clave_estable(identidad)
    estado = (epoca, instancia)  # FK/UNIQUE fijan instancia por cabecera.
    expediente = (estado, caso)  # FK/UNIQUE fijan clave de caso por expediente.
    return estudiante, estado, expediente, clave.encode('utf-8', 'surrogatepass'), str(version), revision, source


@pytest.mark.parametrize('cambio', [
    'ninguno','clave','version','revision','instancia','expediente','source','mayusculas',
])
def test_clave_real_y_proyeccion_relacional_colisionan_igual(contrato_sintetico, cambio):
    original = _verificar_ficticio(contrato_sintetico)
    contrato = contrato_sintetico
    opciones = {}
    if cambio == 'clave':
        contrato = replace(contrato, clave='OTRO_CONTRATO_FICTICIO')
    elif cambio == 'version':
        contrato = replace(contrato, version=2)
    elif cambio == 'revision':
        contrato = replace(contrato, garantias=contrato.garantias + ('OTRA_GARANTIA_FICTICIA',))
    elif cambio == 'instancia':
        opciones['instancia'] = 'OTRA_INSTANCIA_FICTICIA'
    elif cambio == 'expediente':
        opciones['caso'] = 'OTRO_CASO_FICTICIO'
    elif cambio == 'source':
        opciones['source'] = 'OTRO_ID_FICTICIO'
    elif cambio == 'mayusculas':
        opciones['source'] = 'id_ficticio'
    distinto = _verificar_ficticio(contrato, **opciones)
    assert (clave_estable(original) == clave_estable(distinto)) == (cambio == 'ninguno')
    assert (_proyeccion_formal(original) == _proyeccion_formal(distinto)) == (cambio == 'ninguno')


def test_identidad_tiene_namespace_de_estudiante_y_epoca(contrato_sintetico):
    identidad = _verificar_ficticio(contrato_sintetico)
    assert _proyeccion_formal(identidad) != _proyeccion_formal(identidad, estudiante='OTRO_ESTUDIANTE_FICTICIO')
    assert _proyeccion_formal(identidad) != _proyeccion_formal(identidad, epoca='OTRA_EPOCA_FICTICIA')


def test_fks_y_nulls_sostienen_dependencias_funcionales_del_indice():
    act = cuerpo('app.actuaciones')
    assert 'FOREIGN KEY (estudiante_id,estado_id,alcance_instancia_utf8)' in act
    assert 'FOREIGN KEY (estudiante_id,estado_id,expediente_id,alcance_caso_utf8)' in act
    assert 'UNIQUE (estudiante_id,id,instancia_utf8)' in cuerpo('app.estados_reconciliacion')
    assert 'UNIQUE (estudiante_id,estado_id,clave_caso_utf8)' in cuerpo('app.expedientes')
    assert 'alcance_instancia_utf8 IS NOT NULL AND alcance_caso_utf8 IS NOT NULL' in act


def test_cierre_inspecciona_columnas_grupos_y_acceso_al_owner():
    assert 'pg_catalog.pg_attribute' in CODE and 'a.attacl' in CODE
    assert 'privilegio.grantee<>c.relowner' in CODE
    assert 'pg_catalog.has_any_column_privilege(rol,t,permiso)' in CODE
    assert "pg_catalog.pg_has_role(rol,'postgres','USAGE')" in CODE
    assert "pg_catalog.pg_has_role(rol,'postgres','SET')" in CODE
    assert "'MAINTAIN'" in CODE


def test_cota_btree_condicional_no_es_validacion_postgresql():
    # Hipótesis explícitas: MAXALIGN=8, tipos PG17 estándar, sin compresión.
    raw = 3*16 + (512+4) + (128+4) + (64+4) + (128+4)
    cota = ((8 + raw + 7*7 + 7)//8)*8 + 8
    limite_8k = (((8192 - 40 - 16)//3)//8)*8 - 8
    limite_2k = (((2048 - 40 - 16)//3)//8)*8 - 8
    assert raw == 896 and cota == 968 and limite_8k == 2704
    assert limite_2k < cota < limite_8k
    assert 'BETWEEN 1 AND 512' in CODE and 'length(contrato_version_decimal) <= 128' in CODE
    assert "{0,127}" in CODE  # ASCII source_id <=128 octetos por COLLATE C.


def test_ensayo_btree_es_rollback_sin_permisos_extra():
    sql = (ROOT/'supabase/tests/4b1_btree_limites.sql').read_text(encoding='utf-8')
    assert sql.rstrip().endswith('ROLLBACK;')
    assert "current_setting('block_size')::integer <> 8192" in sql
    assert 'INSERT INTO app.actuaciones' in sql
    assert not re.search(r'^\s*(?:ALTER|GRANT|CREATE|DELETE|TRUNCATE|DROP)\b', sql, re.M)


def test_concurrencia_exige_recibo_y_sqlstate_concreto():
    carpeta = ROOT/'supabase/tests'
    preparar = (carpeta/'4b1_concurrencia_preparar.sql').read_text(encoding='utf-8')
    b = (carpeta/'4b1_concurrencia_b.sql').read_text(encoding='utf-8')
    limpiar = (carpeta/'4b1_concurrencia_limpiar.sql').read_text(encoding='utf-8')
    assert 'RETURNING creado_en AS fixture_creado_en \\gset' in preparar
    assert 'WHEN unique_violation' in b and 'CONSTRAINT_NAME' in b
    assert "restriccion<>'una_cabecera_viva'" in b
    assert 'FOR UPDATE NOWAIT' in limpiar and 'prueba_creado' in limpiar
    assert limpiar.index('FOR UPDATE NOWAIT') < limpiar.index('DELETE FROM')
    assert "'4b1c0000-0000-4000-8000-000000000001'" not in limpiar
    assert not re.search(r'^\s*(?:GRANT|ALTER ROLE|SET ROLE)\b', preparar+b+limpiar, re.M)
