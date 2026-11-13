"""Contrato publico minimo, ciclo ASGI y arranque sin secretos ni servicios."""

import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import tomllib
import zipfile

from fastapi.testclient import TestClient
from packaging.requirements import Requirement
import pytest

from tinotify.api import app


def _lineas_requisitos(archivo):
    texto = archivo.read_text(encoding="utf-8").replace("\\\n", " ")
    return [linea.strip() for linea in texto.splitlines()
            if linea.strip() and not linea.lstrip().startswith(("#", "-r"))]


def test_health_devuelve_solo_estado_publico():
    with TestClient(app) as client:
        respuesta = client.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/json"
    assert respuesta.json() == {"status": "ok"}


@pytest.mark.parametrize("ruta", [
    "/", "/docs", "/redoc", "/openapi.json", "/expedientes", "/usuarios", "/sigac",
])
def test_rutas_no_implementadas_no_exponen_datos(ruta):
    with TestClient(app) as client:
        respuesta = client.get(ruta)
    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("metodo", ["POST", "PUT", "DELETE"])
def test_health_no_admite_escrituras(metodo):
    with TestClient(app) as client:
        respuesta = client.request(metodo, "/health")
    assert respuesta.status_code == 405


def test_aplicacion_admite_reiniciar_su_ciclo_asgi():
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}


def test_arranque_desde_paquete_instalado_sin_credenciales(tmp_path):
    # Lista positiva: el hijo no recibe variables PostgreSQL/Supabase/SIGAC,
    # PYTHONPATH ni configuracion del desarrollador. El cwd temporal no tiene .env.
    entorno = {clave: os.environ[clave] for clave in (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG",
    ) if clave in os.environ}
    programa = textwrap.dedent("""
        import socket
        import sys
        from unittest.mock import patch

        def sin_red(*args, **kwargs):
            raise AssertionError("El arranque no debe consultar servicios externos")

        with patch.object(socket, "create_connection", sin_red), \\
             patch.object(socket, "getaddrinfo", sin_red):
            from fastapi.testclient import TestClient
            from tinotify.api import app
            with TestClient(app) as client:
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
            assert not any(name.startswith((
                "tinotify.integrations", "tinotify.persistence", "tinotify.services",
                "psycopg", "asyncpg", "sqlalchemy",
            )) for name in sys.modules)
    """)
    resultado = subprocess.run(
        [sys.executable, "-I", "-B", "-c", programa],
        cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert list(tmp_path.iterdir()) == []


def test_dependencias_fijadas_coinciden_con_manifiesto():
    backend = Path(__file__).resolve().parents[1]
    manifiesto = tomllib.loads((backend/"pyproject.toml").read_text(encoding="utf-8"))

    def requisitos(lineas):
        return {str(Requirement(re.split(r"\s+--hash=", linea)[0].strip()))
                for linea in lineas}

    ejecucion = requisitos(_lineas_requisitos(backend/"requirements.txt"))
    desarrollo = requisitos(_lineas_requisitos(backend/"requirements-dev.txt"))
    assert requisitos(manifiesto["project"]["dependencies"]) <= ejecucion
    assert requisitos(manifiesto["project"]["optional-dependencies"]["dev"]) <= desarrollo
    assert requisitos(manifiesto["dependency-groups"]["local"]) == ejecucion | desarrollo


@pytest.mark.parametrize("archivo", [
    "requirements.txt", "requirements-dev.txt", "requirements-build.txt",
])
def test_requisitos_externos_tienen_pins_y_hashes_sha256(archivo):
    backend = Path(__file__).resolve().parents[1]
    entradas = _lineas_requisitos(backend/archivo)
    assert entradas
    for entrada in entradas:
        pin, *hashes = re.split(r"\s+--hash=sha256:", entrada)
        requisito = Requirement(pin.strip())
        especificadores = list(requisito.specifier)
        assert requisito.url is None and not requisito.extras
        assert len(especificadores) == 1 and especificadores[0].operator == "=="
        assert "*" not in especificadores[0].version
        assert hashes and all(re.fullmatch(r"[0-9a-f]{64}", h.strip()) for h in hashes)


def test_herramientas_de_build_coinciden_con_manifiesto():
    backend = Path(__file__).resolve().parents[1]
    manifiesto = tomllib.loads((backend/"pyproject.toml").read_text(encoding="utf-8"))
    herramientas = {str(Requirement(re.split(r"\s+--hash=", linea)[0].strip()))
                    for linea in _lineas_requisitos(backend/"requirements-build.txt")}
    assert {str(Requirement(r)) for r in manifiesto["build-system"]["requires"]} <= herramientas


def test_pip_rechaza_una_wheel_ficticia_con_hash_alterado(tmp_path):
    wheel = tmp_path/"tinotify_hash_probe-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archivo:
        info = "tinotify_hash_probe-0.0.0.dist-info/"
        archivo.writestr(info+"METADATA", "Metadata-Version: 2.1\nName: tinotify-hash-probe\nVersion: 0.0.0\n")
        archivo.writestr(info+"WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archivo.writestr(info+"RECORD", "")
    requisitos = tmp_path/"requirements-invalidos.txt"
    requisitos.write_text(f"{wheel.as_uri()} --hash=sha256:{'0'*64}\n", encoding="utf-8")
    resultado = subprocess.run([
        sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check",
        "install", "--dry-run", "--no-index", "--no-deps", "--require-hashes",
        "--only-binary=:all:", "-r", str(requisitos),
    ], capture_output=True, text=True, timeout=30, check=False)
    assert resultado.returncode != 0
    assert "DO NOT MATCH THE HASHES" in resultado.stdout + resultado.stderr
