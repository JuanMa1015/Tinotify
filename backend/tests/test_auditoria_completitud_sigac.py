"""Caracteriza riesgos ACTUALES: aprobar estas pruebas no acredita completitud.

Solo transporte simulado, datos ficticios y SQLite temporal. No modifica políticas.
"""

import socket
from uuid import uuid4

import httpx
import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_frontera_persistencia_sigac import servicio
from backend.tests.test_integridad_historial_sigac import (
    bloque, pagina, region, anexos, SEP, cliente_sintetico, USUARIO, CLAVE,
)
from backend.tests.test_sigac_flujo import cliente_servidor, autenticar, html
from backend.tests.test_sqlite_local_v2 import snapshot
from tinotify.domain.actuaciones import TipoCambio
from tinotify.integrations.sigac.lectura_validada import leer_historial_validado, _resolver_lectura
from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.services.ensayo_sigac import ejecutar_ensayo
from tinotify.services.observacion_local import ObservacionRechazada
from tinotify.services.reconciliacion import reconciliar


A = bloque('CONTENIDO_A_SINTETICO')
B = bloque('CONTENIDO_B_SINTETICO', fecha='2018-01-01 10:00:00')
C = bloque('CONTENIDO_C_SINTETICO')
D = bloque('CONTENIDO_D_SINTETICO')


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail('Solo HTTP simulado')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)


def leer(documento, *, total=None):
    with cliente_sintetico([documento], envolver_detalle=False) as (cliente, llamadas):
        cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
        lectura = leer_historial_validado(cliente, 101, total_esperado=total)
        assert len(llamadas) == 7
    return lectura


def documento(*bloques):
    return detalle('<table>' + ''.join(bloques) + '</table>')


@pytest.mark.parametrize('final', ['', SEP])
def test_un_prefijo_bien_cerrado_establece_base_sin_demostrar_completitud(tmp_path, final):
    # El universo ficticio es A,B,C; el servidor solo transmite A y cierra todo.
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    observacion = leer(documento(A, final))
    resultado = s.observar_validada(observacion, clave=uuid4(), generacion_esperada=0)
    assert resultado['baseline'] is True and resultado['actuaciones'] == 1
    assert resultado['novedades_nuevas'] == 0 and len(snapshot(s)['actuaciones']) == 1


def test_dos_subconjuntos_identicos_son_estables_pero_no_completos():
    parcial = documento(A)
    with cliente_sintetico([parcial, parcial], envolver_detalle=False) as (cliente, llamadas):
        resultado = ejecutar_ensayo(cliente, USUARIO, CLAVE, tipo='2', total_casos=1)
        assert len(llamadas) == 9
    assert resultado['resultado'] == 'estable'
    assert resultado['completitud'] == 'completitud_no_verificada'
    assert resultado['actuaciones_por_consulta'] == [1, 1]
    assert resultado['eventos_posteriores'] == 0


@pytest.mark.parametrize('parcial', [documento(A, B), documento(A, B, D)])
def test_ausencias_con_o_sin_novedad_rechazan_actualizacion_sqlite(tmp_path, parcial):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    inicial = leer(documento(A, B, C))
    s.observar_validada(inicial, clave=uuid4(), generacion_esperada=0)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    posterior = leer(parcial)
    _, base = _resolver_lectura(inicial)
    _, actual = _resolver_lectura(posterior)
    estado, _ = reconciliar(None, list(base), caso='CASO_SINTETICO')
    siguiente, resultado = reconciliar(estado, list(actual), caso='CASO_SINTETICO')
    assert {r['local_id'] for r in estado['records']} <= {r['local_id'] for r in siguiente['records']}
    assert all(e.tipo is TipoCambio.CAMBIO_AMBIGUO for e in resultado.eventos)
    with pytest.raises(ObservacionRechazada):
        s.observar_validada(posterior, clave=uuid4(), generacion_esperada=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_superset_de_base_incompleta_se_acepta_aunque_sigan_faltando_actuaciones(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    # C existe en el universo ficticio, pero nunca ha llegado al cliente.
    s.observar_validada(leer(documento(A)), clave=uuid4(), generacion_esperada=0)
    r = s.observar_validada(leer(documento(A, B, D)), clave=uuid4(), generacion_esperada=1)
    assert r['generacion'] == 2 and r['novedades_nuevas'] == 2
    assert len(snapshot(s)['actuaciones']) == 3
    assert all(n['tipo'] == TipoCambio.PRIMERA_OBSERVACION.value for n in s.observaciones()['observaciones'])
    # B tiene fecha antigua: primera observación no implica creación reciente.
    assert all(n['creacion_reciente_acreditada'] is False for n in s.observaciones()['observaciones'])


def test_total_externo_detecta_discordancia_pero_igualdad_no_demuestra_contenido():
    with pytest.raises(SigacClientError) as error:
        leer(documento(A), total=3)  # Total del fixture, no regla operativa fija.
    assert error.value.codigo is CodigoHistorial.TOTAL_DISCORDANTE
    # Mismo total que A,B,C, pero C falta y D lo sustituye: el total se satisface.
    _, actos = _resolver_lectura(leer(documento(A, B, D), total=3))
    assert len(actos) == 3 and not any('CONTENIDO_C_SINTETICO' in a.descripcion for a in actos)


def test_indicio_de_paginacion_no_es_interpretado_ni_se_sigue():
    # Señal inventada SOLO para el fixture: no afirma una ruta/selector de SIGAC.
    pagina_parcial = documento(A).replace('</form>',
        '<nav aria-label="Paginación sintética"><a href="#pagina-sintetica-siguiente">Siguiente</a></nav></form>')
    _, actos = _resolver_lectura(leer(pagina_parcial))
    assert len(actos) == 1  # leer() comprueba que solo hubo 7 solicitudes.


@pytest.mark.parametrize('tipo', ['sin_cierre', 'longitud', 'corte_stream'])
def test_truncamiento_detectable_no_altera_base(tmp_path, tipo):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(documento(A, B)), clave=uuid4(), generacion_esperada=0)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    cuerpo = documento(A)
    esperado = {'sin_cierre': CodigoHistorial.DOCUMENTO_INCOMPLETO,
                'longitud': CodigoHistorial.LONGITUD_RESPUESTA,
                'corte_stream': CodigoHistorial.TRANSPORTE}[tipo]
    class Cortado(httpx.SyncByteStream):
        def __iter__(self):
            yield cuerpo[:60].encode()
            raise httpx.ReadError('INTERRUPCION SINTETICA')
    if tipo == 'sin_cierre':
        respuesta = html(cuerpo.removesuffix('</html>'))
    elif tipo == 'longitud':
        respuesta = httpx.Response(200, content=cuerpo.encode(), headers={
            'content-type': 'text/html', 'content-length': str(len(cuerpo.encode()) + 100)})
    else:
        respuesta = httpx.Response(200, stream=Cortado(), headers={'content-type': 'text/html'})
    with cliente_servidor() as (cliente, servidor):
        autenticar(cliente)
        servidor.cambios['casos.formCaso.con'] = respuesta
        with pytest.raises(SigacClientError) as error:
            lectura = leer_historial_validado(cliente, 101)
            s.observar_validada(lectura, clave=uuid4(), generacion_esperada=1)
        assert error.value.codigo is esperado
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


@pytest.mark.parametrize('tipo', ['anexo_huerfano', 'historia_anidada'])
@pytest.mark.parametrize('previa', [False, True])
def test_estructuras_anidadas_ambiguas_rechazan_sin_modificar_sqlite(tmp_path, tipo, previa):
    # Referencia estructural ficticia: dos tablas hermanas ordinarias dan dos
    # ocurrencias. La etiqueta/ubicación cambia el tratamiento, no los bloques.
    _, referencia = _resolver_lectura(leer(detalle('<table>'+A+'</table><table>'+B+'</table>')))
    assert len(referencia) == 2
    if tipo == 'anexo_huerfano':
        fragmento = '<table>'+A+'</table><table id="tablaAnexos">'+B+'</table>'
    else:
        fragmento = '<table>'+bloque('CONTENIDO_A_SINTETICO<table>'+B+'</table>')+'</table>'
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    if previa:
        s.observar_validada(leer(documento(A)), clave=uuid4(), generacion_esperada=0)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    with pytest.raises(SigacClientError) as error:
        lectura = leer(detalle(fragmento))
        s.observar_validada(lectura, clave=uuid4(), generacion_esperada=int(previa))
    assert error.value.codigo is CodigoHistorial.AMBITO_NO_VERIFICADO
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw


def test_exclusion_interactiva_legitima_y_rechazo_de_historia_dentro_de_controles(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    s.observar_validada(leer(documento(A)), clave=uuid4(), generacion_esperada=0)
    assert s.observar_validada(leer(documento(A, SEP, region())), clave=uuid4(), generacion_esperada=1)['novedades_nuevas'] == 0
    antes = snapshot(s)
    mezcla = region().replace('</textarea>', '</textarea><table>'+B+'</table>')
    with pytest.raises(SigacClientError):
        lectura = leer(documento(A, SEP, mezcla))
        s.observar_validada(lectura, clave=uuid4(), generacion_esperada=2)
    assert snapshot(s) == antes


def test_anexo_sin_enlace_no_elimina_actuacion_pero_cambio_de_metadatos_es_ambiguo(tmp_path):
    s = servicio(tmp_path/'solo-sintetico.sqlite3')
    inicial = leer(documento(bloque('CONTENIDO_A_SINTETICO', extra=anexos())))
    _, actos = _resolver_lectura(inicial)
    assert len(actos) == 1 and len(actos[0].anexos) == 2
    assert any(a.sin_enlace for a in actos[0].anexos)
    s.observar_validada(inicial, clave=uuid4(), generacion_esperada=0)
    antes, raw = snapshot(s), s.almacen.ruta.read_bytes()
    posterior = leer(documento(bloque('CONTENIDO_A_SINTETICO', extra=anexos(sin_enlace=False))))
    with pytest.raises(ObservacionRechazada):
        s.observar_validada(posterior, clave=uuid4(), generacion_esperada=1)
    assert snapshot(s) == antes and s.almacen.ruta.read_bytes() == raw
