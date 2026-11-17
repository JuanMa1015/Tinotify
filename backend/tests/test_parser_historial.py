"""Contrato DOM y compatibilidad: todo el material es sintético y sin red."""

from datetime import datetime
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import socket

import pytest

from tinotify.domain.actuaciones import Actuacion, TipoCambio, VERSION_HUELLA
from tinotify.domain.notificaciones import Prioridad
from tinotify.parsers.parser import ErrorParseoHistorial, PREFIJO_FILAS, parse_actuaciones
from tinotify.persistence.monitor import MonitorActuaciones
from tinotify.services.reconciliacion import reconciliar
from tinotify.services.sigac_service import SigacService


FIXTURES = Path(__file__).parent / "fixtures"


def documento(nombre):
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def documento_con_presentacion():
    """Variante ficticia inequívoca; el original ambiguo se conserva intacto."""
    texto = documento("historial_dom_sintetico.html")
    cambios = (
        ('<tr><td>TITULO_INTERNO_FICTICIO</td><td>ASESOR--&gt;ESTUDIANTE</td></tr>',
         '<tr><td>Título</td><td>TITULO_INTERNO_FICTICIO</td></tr>'),
        ('<tr><td>2020-01-02 10:00:00</td><td>RESPONSABLE_INTERNO_FICTICIO</td></tr>',
         '<tr><td>Fecha y responsable</td><td>2020-01-02 10:00:00 RESPONSABLE_INTERNO_FICTICIO</td></tr>'),
        ('<tr><td>Actuación :</td><td>TEXTO_INTERNO_FICTICIO</td></tr>',
         '<tr><td>Texto</td><td>TEXTO_INTERNO_FICTICIO</td></tr>'),
    )
    for anterior, nuevo in cambios:
        assert texto.count(anterior) == 1
        texto = texto.replace(anterior, nuevo)
    return texto


def fila(etiqueta="Actuación", texto="CONTENIDO_FICTICIO"):
    return f"<tr><td>{escape(etiqueta)} :</td><td>{escape(texto)}</td></tr>"


def bloque(contenido=None, titulo="TITULO_FICTICIO", comunicacion="ASESOR-->ESTUDIANTE",
           fecha="2020-01-01 10:00:00", cabecera=True, anexos=""):
    inicio = '<tr><td colspan="2"><hr></td></tr>'
    if cabecera:
        inicio += f"<tr><td>{escape(titulo)}</td><td>{escape(comunicacion)}</td></tr>"
    return (
        inicio + f"<tr><td>{fecha}</td><td>RESPONSABLE_FICTICIO</td></tr>"
        + (fila() if contenido is None else contenido) + anexos
    )


def tabla(*bloques):
    return "<table>" + "".join(bloques) + "</table>"


def anexo(codigo="CODIGO_FICTICIO_A", descripcion="ANEXO_FICTICIO", archivo="archivo_ficticio.txt",
          referencia=None):
    href = referencia if referencia is not None else f"general.descargarAnexo.con?codigo={codigo}"
    return (
        f"<tr><td>{escape(descripcion)}</td><td>"
        f'<a href="{escape(href, quote=True)}">{escape(archivo)}</a></td></tr>'
    )


def fila_anexos(*entradas):
    return '<tr><td>Anexos :</td><td><table id="tablaAnexos">' + "".join(entradas) + "</table></td></tr>"


def parsear(html, **contexto):
    return parse_actuaciones(html, "CASO_FICTICIO", **contexto)


def filas_descripcion(actuacion):
    assert actuacion.descripcion.startswith(PREFIJO_FILAS)
    contenido = json.loads(actuacion.descripcion.removeprefix(PREFIJO_FILAS))
    assert contenido["parser_content_version"] == 1
    return contenido["filas"]


def test_fixture_dom_delimitado_conserva_tabla_de_presentacion_y_metadatos():
    actuaciones = parsear(documento_con_presentacion(), contenedor_id="historial_ficticio")
    assert len(actuaciones) == 3
    primera, segunda, tercera = actuaciones
    assert primera.etapa == primera.origen == primera.destino == ""
    assert primera.remitente == "RESPONSABLE_FICTICIO"
    filas = filas_descripcion(primera)
    assert [etiqueta for etiqueta, _ in filas] == [
        "Actuación", "Reparto", "Creación de cita", "Campo ficticio",
    ]
    assert filas[0][1] == "CONTENIDO_FICTICIO_A\nCONTENIDO_FICTICIO_B"
    assert "TEXTO_INTERNO_FICTICIO" in filas[1][1]
    assert filas[-1][1] == ""
    assert "archivo_ficticio" not in primera.descripcion
    assert len(primera.anexos) == 3
    assert primera.anexos[0] == primera.anexos[1]
    assert segunda.etapa == segunda.origen == segunda.destino == ""
    assert filas_descripcion(segunda)[0][0] == "Relación de los hechos"
    assert tercera.descripcion == "CONTENIDO_FICTICIO_SIMPLE"
    assert all(a.identificador_origen is None for a in actuaciones)


@pytest.mark.parametrize("titulo,comunicacion", [
    ("", ""), ("TITULO_FICTICIO", ""), ("", "ASESOR-->ESTUDIANTE"),
])
def test_campos_opcionales(titulo, comunicacion):
    a = parsear(tabla(bloque(titulo=titulo, comunicacion=comunicacion)))[0]
    assert a.etapa == titulo
    assert a.origen == ("ASESOR" if comunicacion else "")
    assert a.destino == ("ESTUDIANTE" if comunicacion else "")


def test_cabecera_opcional_sin_fila_de_titulo():
    a = parsear(tabla(bloque(cabecera=False)))[0]
    assert a.etapa == a.origen == a.destino == ""


@pytest.mark.parametrize("etiqueta", [
    "Reparto", "Creación de cita", "Relación de los hechos", "CATEGORIA_FICTICIA_NUEVA",
])
def test_etiquetas_variables_preservadas(etiqueta):
    a = parsear(tabla(bloque(contenido=fila(etiqueta))))[0]
    assert filas_descripcion(a) == [[etiqueta, "CONTENIDO_FICTICIO"]]


def test_filas_repetidas_vacias_y_sin_etiqueta():
    contenido = fila("Reparto", "") * 2 + fila("", "VALOR_FICTICIO")
    a = parsear(tabla(bloque(contenido=contenido)))[0]
    assert filas_descripcion(a) == [["Reparto", ""], ["Reparto", ""], ["", "VALOR_FICTICIO"]]


@pytest.mark.parametrize("posicion", [0, 1, 2])
def test_cambio_en_cualquier_fila_modifica_huella(posicion):
    originales = [("Actuación", "A_FICTICIO"), ("Reparto", "B_FICTICIO"), ("Campo ficticio", "C_FICTICIO")]
    modificadas = originales.copy()
    etiqueta, texto = modificadas[posicion]
    modificadas[posicion] = etiqueta, texto + "_CAMBIO"
    a = parsear(tabla(bloque(contenido="".join(fila(*f) for f in originales))))[0]
    b = parsear(tabla(bloque(contenido="".join(fila(*f) for f in modificadas))))[0]
    assert a.huella_version != b.huella_version


def test_cambiar_etiqueta_o_orden_modifica_huella():
    a = parsear(tabla(bloque(contenido=fila("Reparto", "A") + fila("Campo ficticio", "B"))))[0]
    b = parsear(tabla(bloque(contenido=fila("Campo ficticio", "B") + fila("Reparto", "A"))))[0]
    c = parsear(tabla(bloque(contenido=fila("Otra categoria", "A") + fila("Campo ficticio", "B"))))[0]
    assert len({a.huella_version, b.huella_version, c.huella_version}) == 3


def test_cambiar_categoria_simple_no_colisiona_con_actuacion():
    a = parsear(tabla(bloque()))[0]
    b = parsear(tabla(bloque(contenido=fila("Reparto"))))[0]
    assert a.huella_version != b.huella_version


def test_prefijo_reservado_en_texto_no_colisiona_con_filas_serializadas():
    a = parsear(tabla(bloque(contenido=fila("Reparto"))))[0]
    b = parsear(tabla(bloque(contenido=fila(texto=a.descripcion))))[0]
    assert a.descripcion != b.descripcion
    assert filas_descripcion(b) == [["Actuación", a.descripcion]]


def test_compatibilidad_exacta_de_contenido_y_huellas_simples():
    a = parsear(tabla(bloque()))[0]
    esperada = Actuacion("TITULO_FICTICIO", "ASESOR", "ESTUDIANTE", datetime(2020, 1, 1, 10),
                        "RESPONSABLE_FICTICIO", "CONTENIDO_FICTICIO")
    legacy = "\x1f".join(("CASO_FICTICIO", esperada.fecha.isoformat(), "ASESOR", "ESTUDIANTE",
                           "RESPONSABLE_FICTICIO", "CONTENIDO_FICTICIO"))
    assert a.descripcion == esperada.descripcion
    assert a.huella_version == esperada.huella_version
    assert a.huella == sha256(legacy.encode()).hexdigest()
    assert VERSION_HUELLA == 1


def test_formulario_con_cabecera_historica_no_se_omite():
    formulario = tabla(bloque(contenido=fila(texto="") + '<tr><td>Campo:</td><td><textarea>BORRADOR_FICTICIO</textarea></td></tr>'))
    with pytest.raises(ErrorParseoHistorial):
        parsear('<form method="post">' + formulario + '</form>')


def test_historial_dentro_de_formulario_global_sin_controles_propios():
    assert len(parsear('<form><input name="campo" value="FICTICIO">' + tabla(bloque()) + '</form>')) == 1


def test_formulario_antes_del_primer_separador_en_misma_tabla():
    formulario = '<tr><td>CREAR FICTICIO</td><td><textarea>BORRADOR_FICTICIO</textarea></td></tr>'
    assert len(parsear(tabla(formulario, bloque()))) == 1


def test_formulario_mezclado_en_historial_rechaza_resultado_parcial():
    formulario = bloque(contenido='<tr><td>Actuación :</td><td><textarea>BORRADOR_FICTICIO</textarea></td></tr>')
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(), formulario))


def test_tablas_de_layout_y_otras_tablas_no_duplican_historial():
    otro = '<table><tr><td><hr></td></tr><tr><td>OTRO_CONTENIDO_FICTICIO</td></tr></table>'
    html = '<table><tr><td>' + otro + '<section id="historial_ficticio">' + tabla(bloque()) + '</section></td></tr></table>'
    assert len(parsear(html, contenedor_id="historial_ficticio")) == 1


def test_hr_dentro_de_contenido_no_separa_bloques():
    contenido = '<tr><td>Actuación :</td><td>A_FICTICIO<hr>B_FICTICIO</td></tr>'
    a = parsear(tabla(bloque(contenido=contenido)))[0]
    assert a.descripcion == "A_FICTICIO\nB_FICTICIO"


def test_tbody_distintos_y_fragmentos_historial_legacy():
    partes = bloque().split('</tr>', 1)
    html = '<table><tbody>' + partes[0] + '</tr></tbody><tbody>' + partes[1] + '</tbody></table>'
    assert len(parsear(html + tabla(bloque()))) == 2


def test_espaciadores_y_separador_final_no_crean_bloques():
    espaciador = '<tr><td colspan="2"> </td></tr>'
    html = tabla(espaciador + bloque() + espaciador
                 + '<tr><td colspan="2"><hr></td></tr><tr><td></td><td></td></tr>')
    assert len(parsear(html)) == 1


def test_separador_del_contenedor_con_dos_celdas():
    html = tabla(bloque()).replace('<td colspan="2"><hr></td>', '<td></td><td><hr></td>')
    assert len(parsear(html)) == 1


def test_duplicados_conservan_multiplicidad_sin_identidad_de_origen():
    entradas = parsear(tabla(bloque(), bloque()))
    assert entradas[0] == entradas[1]
    estado, base = reconciliar(None, entradas, caso="CASO_FICTICIO")
    assert len(estado["records"]) == 2
    assert len({r["local_id"] for r in estado["records"]}) == 2
    assert base.eventos == ()
    aumentado, cambio = reconciliar(estado, parsear(tabla(bloque(), bloque(), bloque())), caso="CASO_FICTICIO")
    assert len(aumentado["records"]) == 3
    assert [evento.tipo for evento in cambio.eventos] == [TipoCambio.PRIMERA_OBSERVACION]
    assert all(r["source_id"] is r["contract_ref"] is r["origin_scope"] is None for r in aumentado["records"])


def test_reordenar_bloques_no_crea_eventos_y_conserva_orden_de_extraccion():
    a, b = bloque(contenido=fila(texto="A_FICTICIO")), bloque(contenido=fila(texto="B_FICTICIO"))
    estado, _ = reconciliar(None, parsear(tabla(a, b)), caso="CASO_FICTICIO")
    entradas = parsear(tabla(b, a))
    assert entradas[0].descripcion == "B_FICTICIO"
    _, resultado = reconciliar(estado, entradas, caso="CASO_FICTICIO")
    assert resultado.eventos == ()


@pytest.mark.parametrize("posicion", [0, 1, 2])
def test_insercion_en_cualquier_posicion(posicion):
    existentes = [bloque(contenido=fila(texto="A_FICTICIO")), bloque(contenido=fila(texto="B_FICTICIO"))]
    estado, _ = reconciliar(None, parsear(tabla(*existentes)), caso="CASO_FICTICIO")
    existentes.insert(posicion, bloque(contenido=fila(texto="C_FICTICIO")))
    _, cambio = reconciliar(estado, parsear(tabla(*existentes)), caso="CASO_FICTICIO")
    assert [e.tipo for e in cambio.eventos] == [TipoCambio.PRIMERA_OBSERVACION]


def test_anexos_despues_de_varias_filas_y_en_varias_tablas():
    contenido = fila("Actuación") + fila("Reparto")
    a = parsear(tabla(bloque(contenido=contenido, anexos=fila_anexos(anexo()) + fila_anexos(anexo()))))[0]
    assert len(a.anexos) == 2
    assert a.anexos[0] == a.anexos[1]
    assert "archivo_ficticio" not in a.descripcion


def test_anexo_dentro_de_celda_de_contenido_no_contamina_descripcion():
    contenido = '<tr><td>Actuación :</td><td>CONTENIDO_FICTICIO<table id="tablaAnexos">' + anexo() + '</table></td></tr>'
    a = parsear(tabla(bloque(contenido=contenido)))[0]
    assert a.descripcion == "CONTENIDO_FICTICIO"
    assert len(a.anexos) == 1


def test_reordenar_anexos_no_cambia_version_pero_duplicarlos_si():
    a, b = anexo(), anexo(codigo="CODIGO_FICTICIO_B")
    extraer = lambda entradas: parsear(tabla(bloque(anexos=fila_anexos(*entradas))))[0]
    assert extraer([a, b]).huella_version == extraer([b, a]).huella_version
    assert extraer([a, b]).huella_version != extraer([a, a, b]).huella_version


@pytest.mark.parametrize("metadato", ["codigo", "descripcion", "archivo"])
def test_cambiar_metadato_de_anexo_cambia_version(metadato):
    a = parsear(tabla(bloque(anexos=fila_anexos(anexo()))))[0]
    b = parsear(tabla(bloque(anexos=fila_anexos(anexo(**{metadato: "OTRO_VALOR_FICTICIO"})))))[0]
    assert a.huella_version != b.huella_version
    assert a.huella == b.huella  # Interfaz legacy, no usada por reconciliación.
    assert a.identificador_origen is b.identificador_origen is None


def test_anadir_y_quitar_anexo_cambia_version():
    a = parsear(tabla(bloque()))[0]
    b = parsear(tabla(bloque(anexos=fila_anexos(anexo()))))[0]
    assert a.huella_version != b.huella_version


@pytest.mark.parametrize("href", [
    "https://example.invalid/general.descargarAnexo.con?codigo=FICTICIO",
    "//example.invalid/general.descargarAnexo.con?codigo=FICTICIO",
    "javascript:CODIGO_FICTICIO",
    "../general.descargarAnexo.con?codigo=FICTICIO",
    "/general.descargarAnexo.con?codigo=FICTICIO",
    "otro/general.descargarAnexo.con?codigo=FICTICIO",
    "general.descargarAnexo.con",
    "general.descargarAnexo.con?codigo=",
    "general.descargarAnexo.con?codigo=FICTICIO&codigo=OTRO",
    "general.descargarAnexo.con?codigo=FICTICIO&extra=OTRO",
    "general.descargarAnexo.con?codigo=FICTICIO#fragmento",
    "general.descargarAnexo.con?codigo=FICTICIO#",
    "general.descargarAnexo.con?codigo=%0A",
    "general.descargarAnexo.con?codigo=%ZZ",
    "general.descargarAnexo.con?codigo=%FF",
])
def test_referencia_invalida_no_se_descarta_silenciosamente(href):
    with pytest.raises(ErrorParseoHistorial) as error:
        parsear(tabla(bloque(anexos=fila_anexos(anexo(referencia=href)))))
    assert href not in str(error.value)


def test_anexo_roto_rechaza_todo_el_historial():
    roto = '<tr><td>Anexos :</td><td><table id="tablaAnexos"><tr><td>FICTICIO</td></tr></table></td></tr>'
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(), bloque(anexos=roto)))


def test_parser_nunca_abre_conexiones(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("No debe abrir conexiones")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket.socket, "connect", prohibido)
    assert len(parsear(documento_con_presentacion(), contenedor_id="historial_ficticio")) == 3


def test_html_malformado_recuperable():
    a = parsear(documento("historial_malformado_recuperable.html"))[0]
    assert filas_descripcion(a) == [["Reparto", "CONTENIDO_FICTICIO"]]


def test_html_malformado_ambiguo_rechaza_todo():
    with pytest.raises(ErrorParseoHistorial):
        parsear(documento("historial_malformado_ambiguo.html"))


def test_separador_ausente_no_fusiona_dos_actuaciones():
    segundo = bloque(fecha="2020-01-02 10:00:00").replace('<tr><td colspan="2"><hr></td></tr>', '', 1)
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(), segundo))


def test_primer_separador_ausente_no_omite_bloque_historico():
    primero = bloque().replace('<tr><td colspan="2"><hr></td></tr>', '', 1)
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(primero, bloque(fecha="2020-01-02 10:00:00")))


@pytest.mark.parametrize("fecha", ["2020-99-01 10:00:00", "FECHA_FICTICIA_ILEGIBLE"])
def test_fecha_rota_no_permite_resultado_parcial(fecha):
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(), bloque(fecha=fecha)))


@pytest.mark.parametrize("comunicacion", ["ASESOR", "ASESOR-->", "-->ESTUDIANTE", "A-->B-->C"])
def test_comunicacion_no_vacia_ininterpretable_rechaza(comunicacion):
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(comunicacion=comunicacion)))


def test_error_de_parseo_no_escribe_estado(tmp_path):
    casos = '<table class="tabla"><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr><tr onclick="abrir(12345)" class="fila_enlace"><td>12345</td><td>CLIENTE FICTICIO</td><td>ESTADO FICTICIO</td></tr></table>'
    ruta = tmp_path / "estado_ficticio.json"
    monitor = MonitorActuaciones(ruta)
    servicio = SigacService(monitor)
    servicio.procesar(casos, {12345: tabla(bloque())})
    anterior = ruta.read_bytes()
    with pytest.raises(ErrorParseoHistorial):
        servicio.procesar(casos, {12345: documento("historial_malformado_ambiguo.html")})
    assert ruta.read_bytes() == anterior


def test_error_de_primera_extraccion_no_crea_estado(tmp_path):
    casos = '<table class="tabla"><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr><tr onclick="abrir(12345)" class="fila_enlace"><td>12345</td><td>CLIENTE FICTICIO</td><td>ESTADO FICTICIO</td></tr></table>'
    ruta = tmp_path / "estado_ficticio.json"
    servicio = SigacService(MonitorActuaciones(ruta))
    with pytest.raises(ErrorParseoHistorial):
        servicio.procesar(casos, {12345: documento("historial_malformado_ambiguo.html")})
    assert not ruta.exists()


def test_estado_v22_simple_preexistente_no_requiere_transicion(tmp_path):
    ruta = tmp_path / "estado_ficticio.json"
    anterior = Actuacion("TITULO_FICTICIO", "ASESOR", "ESTUDIANTE", datetime(2020, 1, 1, 10),
                        "RESPONSABLE_FICTICIO", "CONTENIDO_FICTICIO")
    monitor = MonitorActuaciones(ruta)
    monitor.sincronizar("CASO_FICTICIO", [anterior])
    original = ruta.read_bytes()
    monitor = MonitorActuaciones(ruta)
    assert monitor.sincronizar("CASO_FICTICIO", parsear(tabla(bloque()))) == []
    assert ruta.read_bytes() == original


def test_estado_con_contenido_antes_omitido_solo_permite_ambiguedad():
    anterior = Actuacion("TITULO_FICTICIO", "ASESOR", "ESTUDIANTE", datetime(2020, 1, 1, 10),
                        "RESPONSABLE_FICTICIO", "CONTENIDO_FICTICIO")
    estado, _ = reconciliar(None, [anterior], caso="CASO_FICTICIO")
    nuevo = parsear(tabla(bloque(contenido=fila() + fila("Reparto", "OTRO_FICTICIO"))))
    siguiente, resultado = reconciliar(estado, nuevo, caso="CASO_FICTICIO")
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.CAMBIO_AMBIGUO]
    assert len(siguiente["records"]) == 2
    assert len(estado["records"]) == 1  # El motor puro no migra ni modifica su entrada.


@pytest.mark.parametrize("historiales,esperados", [
    ([["A", "A"], ["A"], ["A", "A"]], [0, 0, 0]),
    ([["A"], ["B"], ["A"]], [0, 1, 0]),
])
def test_secuencias_de_reaparicion(historiales, esperados):
    estado = None
    eventos = []
    for textos in historiales:
        entradas = parsear(tabla(*(bloque(contenido=fila(texto=t + "_FICTICIO")) for t in textos)))
        estado, resultado = reconciliar(estado, entradas, caso="CASO_FICTICIO")
        eventos.append(len(resultado.eventos))
    assert eventos == esperados


def test_v22_reinicio_ambiguo_sin_comunicacion_y_sin_avisos_repetidos(tmp_path):
    ruta = tmp_path / "estado_ficticio.json"
    html = tabla(bloque(contenido=fila("Reparto", "A_FICTICIO"), comunicacion=""))
    cambio = html.replace("A_FICTICIO", "B_FICTICIO")
    monitor = MonitorActuaciones(ruta)
    assert monitor.sincronizar("CASO_FICTICIO", parsear(html)) == []
    monitor = MonitorActuaciones(ruta)
    resultado = monitor.reconciliar("CASO_FICTICIO", parsear(cambio))
    assert [e.tipo for e in resultado.eventos] == [TipoCambio.CAMBIO_AMBIGUO]
    assert monitor.notificaciones("CASO_FICTICIO", resultado)[0].prioridad == Prioridad.NORMAL
    monitor = MonitorActuaciones(ruta)
    assert monitor.sincronizar("CASO_FICTICIO", parsear(cambio)) == []
    estado = json.loads(ruta.read_text(encoding="utf-8"))
    assert estado["schema_version"] == estado["state_revision"] == 2
    assert estado["fingerprint_version"] == 1
    assert all(r["source_id"] is None for r in estado["cases"]["CASO_FICTICIO"]["records"])


def test_unicode_y_serializacion_determinista():
    contenido = fila("Creación de cita", "VALOR_FICTICIO_CAFÉ") + fila("Reparto", "OTRO_FICTICIO")
    html = tabla(bloque(contenido=contenido))
    descompuesto = html.replace("é", "e\u0301").replace("ó", "o\u0301")
    a, b = parsear(html)[0], parsear(descompuesto)[0]
    assert a.huella_version == b.huella_version
    assert parsear(html)[0] == a


def test_lineas_crlf_y_lf_en_contenido_estructurado_son_equivalentes():
    contenido = fila("Reparto", "LINEA_FICTICIA_A\r\nLINEA_FICTICIA_B")
    a = parsear(tabla(bloque(contenido=contenido)))[0]
    b = parsear(tabla(bloque(contenido=contenido.replace("\r\n", "\n"))))[0]
    assert a.descripcion == b.descripcion
    assert a.huella_version == b.huella_version


def tabla_historica_irreconocible():
    return tabla(bloque(fecha="FECHA_FICTICIA_ILEGIBLE", contenido=fila("CATEGORIA_FICTICIA_NUEVA")))


def test_dos_tablas_historicas_una_irreconocible_no_devuelven_extraccion_parcial():
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque()) + tabla_historica_irreconocible())


@pytest.mark.parametrize("orden", [0, 1])
def test_contenedor_completo_valida_todas_sus_tablas(orden):
    tablas = [tabla(bloque()), tabla_historica_irreconocible()]
    if orden:
        tablas.reverse()
    with pytest.raises(ErrorParseoHistorial):
        parsear('<section id="ambito_ficticio">' + ''.join(tablas) + '</section>', contenedor_id="ambito_ficticio")


def test_tabla_ajena_fuera_del_contenedor_no_se_rechaza():
    html = tabla_historica_irreconocible() + '<section id="ambito_ficticio">' + tabla(bloque()) + '</section>'
    assert len(parsear(html, contenedor_id="ambito_ficticio")) == 1


def test_tabla_sin_separadores_dentro_del_contenedor_no_se_omite():
    desconocida = '<table><tr><td>ESTRUCTURA_FICTICIA_DESCONOCIDA</td></tr></table>'
    with pytest.raises(ErrorParseoHistorial):
        parsear('<section id="ambito_ficticio">' + tabla(bloque()) + desconocida + '</section>', contenedor_id="ambito_ficticio")


def test_pagina_mixta_sin_frontera_no_se_declara_completa():
    desconocida = '<table><tr><td>OTRA_SECCION_FICTICIA</td></tr></table>'
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque()) + desconocida)


def test_controles_sin_formulario_no_ocultan_tabla_ilegible():
    desconocida = tabla_historica_irreconocible().replace('CONTENIDO_FICTICIO', '<input value="FICTICIO">')
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque()) + desconocida)


def test_formulario_dentro_del_ambito_explicito_no_se_omite():
    desconocida = '<form>' + tabla_historica_irreconocible().replace('CONTENIDO_FICTICIO', '<input value="FICTICIO">') + '</form>'
    with pytest.raises(ErrorParseoHistorial):
        parsear('<section id="ambito_ficticio">' + tabla(bloque()) + desconocida + '</section>', contenedor_id="ambito_ficticio")


def test_extraccion_intertablas_invalida_conserva_estado(tmp_path):
    casos = '<table class="tabla"><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr><tr onclick="abrir(12345)" class="fila_enlace"><td>12345</td><td>CLIENTE FICTICIO</td><td>ESTADO FICTICIO</td></tr></table>'
    ruta = tmp_path / 'estado_ficticio.json'
    servicio = SigacService(MonitorActuaciones(ruta))
    servicio.procesar(casos, {12345: tabla(bloque())})
    anterior = ruta.read_bytes()
    with pytest.raises(ErrorParseoHistorial):
        servicio.procesar(casos, {12345: tabla(bloque()) + tabla_historica_irreconocible()})
    assert ruta.read_bytes() == anterior


@pytest.mark.parametrize("html", [
    '<section id="otro_ficticio"></section>',
    '<section id="ambito_ficticio"></section><section id="ambito_ficticio"></section>',
])
def test_contenedor_ausente_o_duplicado_no_tiene_fallback(html):
    with pytest.raises(ErrorParseoHistorial):
        parsear(html + tabla(bloque()), contenedor_id="ambito_ficticio")


def test_tabla_de_anexos_no_se_acepta_como_contenedor_historico():
    with pytest.raises(ErrorParseoHistorial):
        parsear(tabla(bloque(anexos=fila_anexos(anexo()))), contenedor_id="tablaAnexos")


@pytest.mark.parametrize("etiqueta", ["Actuación", "Reparto"])
@pytest.mark.parametrize("contenido", [
    '<strong>TEXTO</strong> FICTICIO',
    '<span>TEXTO FICTICIO</span>',
    '<b>TEXTO</b> <em>FICTICIO</em>',
    '<div>TEXTO FICTICIO</div>',
    '<span class="ficticia" style="color:red">TEXTO FICTICIO</span>',
    '  TEXTO FICTICIO  ',
])
def test_presentaciones_inline_equivalentes_no_cambian_version(etiqueta, contenido):
    def extraer(valor):
        return parsear(tabla(bloque(contenido=f'<tr><td>{etiqueta} :</td><td>{valor}</td></tr>')))[0]
    assert extraer(contenido).huella_version == extraer('TEXTO FICTICIO').huella_version


@pytest.mark.parametrize("contenido", [
    'TEXTO<br>FICTICIO', 'TEXTO<br/><br/>FICTICIO',
    '<p>TEXTO</p><p>FICTICIO</p>', '<div>TEXTO</div><div>FICTICIO</div>',
    '<p>TEXTO</p>\n    <p>FICTICIO</p>',
    '<div>TEXTO</div>   <div>FICTICIO</div>',
])
def test_saltos_estructurales_equivalentes(contenido):
    def extraer(valor):
        return parsear(tabla(bloque(contenido=f'<tr><td>Reparto :</td><td>{valor}</td></tr>')))[0]
    assert extraer(contenido).huella_version == extraer('TEXTO\nFICTICIO').huella_version


@pytest.mark.parametrize("contenido", [
    'TEXTO  FICTICIO', 'TEXTO\tFICTICIO', 'TEXTO\nFICTICIO',
    'TEXTO\n\nFICTICIO', 'TEXTOFICTICIO', 'TEXTO OTRO_FICTICIO',
    'TEXTO&nbsp;FICTICIO',
])
def test_diferencias_reales_del_texto_se_conservan(contenido):
    def extraer(valor):
        return parsear(tabla(bloque(contenido=f'<tr><td>Reparto :</td><td>{valor}</td></tr>')))[0]
    assert extraer(contenido).huella_version != extraer('TEXTO FICTICIO').huella_version


def test_lineas_vacias_del_texto_no_se_truncan():
    def extraer(valor):
        return parsear(tabla(bloque(contenido=fila("Reparto", valor))))[0]
    assert extraer('A\n\n\nB').huella_version != extraer('A\n\nB').huella_version


def test_fragmentar_palabras_con_etiquetas_inline_no_inventa_espacios():
    a = parsear(tabla(bloque(contenido='<tr><td>Re<span>par</span>to :</td><td>TEX<strong>TO</strong> FICTICIO</td></tr>')))[0]
    b = parsear(tabla(bloque(contenido=fila('Reparto', 'TEXTO FICTICIO'))))[0]
    assert a.huella_version == b.huella_version


def test_presentacion_inline_de_metadatos_no_cambia_version():
    html = tabla(bloque(anexos=fila_anexos(anexo())))
    modificado = (
        html.replace('TITULO_FICTICIO', '<strong>TITULO_</strong>FICTICIO')
        .replace('RESPONSABLE_FICTICIO', '<span>RESPONSABLE_</span>FICTICIO')
        .replace('ASESOR--&gt;ESTUDIANTE', '<b>ASESOR</b>--&gt;<em>ESTUDIANTE</em>')
        .replace('archivo_ficticio.txt</a>', '<span>archivo_</span>ficticio.txt</a>')
    )
    assert parsear(html)[0].huella_version == parsear(modificado)[0].huella_version
