from dataclasses import replace
from datetime import datetime
from pathlib import Path
import unicodedata

import pytest

from tinotify.domain.actuaciones import IdentificadorSigac, adaptar_observacion, serializar
from tinotify.parsers.parser import parse_actuaciones


@pytest.mark.parametrize("campo,valor", [
    ("etapa", "OTRA ETAPA FICTICIA"), ("origen", "DIRECCION"), ("destino", "ASESOR"),
    ("fecha", datetime(2020, 1, 2)), ("remitente", "OTRO REMITENTE FICTICIO"),
    ("descripcion", "OTRA DESCRIPCIÓN FICTICIA"),
])
def test_version_incluye_cada_campo(actuacion_ficticia, campo, valor):
    original = actuacion_ficticia()
    assert replace(original, **{campo: valor}).huella_version != original.huella_version


def test_unicode_y_saltos_de_linea_canonicos(actuacion_ficticia):
    a = actuacion_ficticia(descripcion="Revisión ficticia\nlínea ficticia")
    b = replace(a, descripcion=unicodedata.normalize("NFD", a.descripcion).replace("\n", "\r\n"))
    assert a.huella_version == b.huella_version


def test_espacios_del_contenido_no_se_eliminan(actuacion_ficticia):
    a = actuacion_ficticia(descripcion="texto ficticio")
    assert replace(a, descripcion="texto  ficticio").huella_version != a.huella_version


def test_roles_normalizan_mayusculas_y_bordes(actuacion_ficticia):
    a = actuacion_ficticia()
    assert replace(a, origen=" asesor ", destino=" estudiante ").huella_version == a.huella_version


def test_serializacion_estructurada_no_confunde_separadores(actuacion_ficticia):
    a = actuacion_ficticia(remitente="a\x1fb", descripcion="c")
    b = actuacion_ficticia(remitente="a", descripcion="b\x1fc")
    assert a.huella_version != b.huella_version
    assert serializar({"b": 1, "a": 2}) == serializar({"a": 2, "b": 1})
    assert a.contenido_versionado()["fingerprint_version"] == 1


def test_identidad_origen_y_huella_legacy_no_son_version(actuacion_ficticia):
    a = actuacion_ficticia()
    b = actuacion_ficticia(id_origen="FICTICIO-A", huella="LEGACY FICTICIA")
    assert a.huella_version == b.huella_version


@pytest.mark.parametrize("campo,valor", [
    ("descripcion", "OTRA DESCRIPCIÓN FICTICIA"),
    ("archivo", "otro_archivo_ficticio.txt"),
    ("referencia", "general.descargarAnexo.con?codigo=OTRO_FICTICIO"),
])
def test_anexos_modificados_cambian_version(actuacion_ficticia, anexo_ficticio, campo, valor):
    a = actuacion_ficticia(anexos=(anexo_ficticio,))
    b = replace(a, anexos=(replace(anexo_ficticio, **{campo: valor}),))
    assert a.huella_version != b.huella_version


def test_anexos_agregados_retirados_reordenados_y_repetidos(actuacion_ficticia, anexo_ficticio):
    segundo = replace(anexo_ficticio, archivo="segundo_ficticio.txt")
    a = actuacion_ficticia()
    uno = replace(a, anexos=(anexo_ficticio,))
    dos = replace(a, anexos=(anexo_ficticio, segundo))
    assert len({a.huella_version, uno.huella_version, dos.huella_version}) == 3
    assert replace(dos, anexos=tuple(reversed(dos.anexos))).huella_version == dos.huella_version
    assert replace(uno, anexos=(anexo_ficticio, anexo_ficticio)).huella_version != uno.huella_version


def test_parser_legacy_compatible_y_version_completa():
    html = (Path(__file__).parent / "fixtures/caso_prueba.html").read_text(encoding="utf-8")
    a = parse_actuaciones(html, "CASO_FICTICIO")[0]
    b = parse_actuaciones(html.replace("Documento de prueba", "OTRO ANEXO FICTICIO"), "CASO_FICTICIO")[0]
    assert a.huella == b.huella  # Propiedad legacy conservada, no usada por v2.
    assert a.huella_version != b.huella_version
    con_atributo = html.replace("<table>", '<table data-actuacion-id="FICTICIO-NO-VALIDADO">', 1)
    assert parse_actuaciones(con_atributo, "CASO_FICTICIO")[0].identificador_origen is None


@pytest.mark.parametrize("valor", ["", " ", "a b", "https://example.invalid", "a?b", "a/b", "á", "a" * 129, None, 1])
def test_identificador_rechaza_sintaxis_no_validada(valor):
    with pytest.raises(ValueError):
        IdentificadorSigac(valor)


def test_id_crudo_no_se_acepta_como_contrato(actuacion_ficticia):
    with pytest.raises(ValueError):
        actuacion_ficticia(identificador_origen="FICTICIO-CRUDO")


@pytest.mark.parametrize("campo", ["etapa", "remitente", "descripcion"])
def test_unicode_normalizado_en_campos_textuales(actuacion_ficticia, campo):
    a = actuacion_ficticia(**{campo: "Revisión ficticia"})
    b = replace(a, **{campo: unicodedata.normalize("NFD", "Revisión ficticia")})
    assert a.huella_version == b.huella_version


def test_unicode_normalizado_en_anexos(actuacion_ficticia, anexo_ficticio):
    a = actuacion_ficticia(anexos=(replace(anexo_ficticio, descripcion="Revisión ficticia"),))
    b = replace(a, anexos=(replace(a.anexos[0], descripcion=unicodedata.normalize("NFD", "Revisión ficticia")),))
    assert a.huella_version == b.huella_version


@pytest.mark.parametrize("entrada", [
    None, {}, {"fecha": "no-fecha", "direccion": "ASESOR-->ESTUDIANTE", "descripcion": "FICTICIA"},
    {"fecha": "2020-01-01", "direccion": "OTRO", "descripcion": "FICTICIA"},
    {"fecha": "2020-01-01", "direccion": "-->ESTUDIANTE", "descripcion": "FICTICIA"},
    {"fecha": "2020-01-01", "direccion": "ASESOR-->ESTUDIANTE", "descripcion": "FICTICIA", "campo_desconocido": "FICTICIO"},
])
def test_entrada_invalida_no_se_adapta(entrada):
    with pytest.raises(ValueError):
        adaptar_observacion(entrada)
