"""`_termina_en_html` (sin retroceso catastrófico) equivale a la expresión anterior en casos normales. Datos ficticios."""

import re
import time

import pytest

from tinotify.integrations.sigac.sigac_respuestas import _termina_en_html

ANTIGUA = re.compile(r"</html\s*>\s*(?:<!--.*?-->\s*)*$", re.I | re.S)


@pytest.mark.parametrize("html", [
    "<html></html>", "<html></HTML  >\n", "<html></html><!-- a -->", "<html></html> <!-- a -->\n<!-- b -->  ",
    "<html></html><!-- sin cierre", "<html></html>texto", "<html></html><!-- a -->x", "sin cierre", "",
    "</html></html>", "</html>x</html>", "</html><!--a--></html>", "</html\n>\t", "<html></html><!---->",
])
def test_equivale_a_la_expresion_anterior(html):
    assert _termina_en_html(html) == bool(ANTIGUA.search(html))


def test_entrada_hostil_no_se_cuelga():
    for hostil in ("</html>" + "<!--" * 50000, "</html>" + "<!-- a -->" * 30000 + "x", "</html" + " " * 200000, "<!--" * 100000):
        t = time.perf_counter()
        _termina_en_html(hostil)
        assert time.perf_counter() - t < 1.0
