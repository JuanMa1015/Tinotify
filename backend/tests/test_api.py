"""Contrato publico minimo, ciclo ASGI y arranque sin secretos ni servicios."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import tomllib

from fastapi.testclient import TestClient
from packaging.requirements import Requirement
import pytest

from tinotify.api import app


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
        return {str(Requirement(linea)) for linea in lineas
                if linea.strip() and not linea.startswith(("#", "-r"))}

    ejecucion = requisitos((backend/"requirements.txt").read_text().splitlines())
    desarrollo = requisitos((backend/"requirements-dev.txt").read_text().splitlines())
    assert requisitos(manifiesto["project"]["dependencies"]) <= ejecucion
    assert requisitos(manifiesto["project"]["optional-dependencies"]["dev"]) <= desarrollo
    assert requisitos(manifiesto["dependency-groups"]["local"]) == ejecucion | desarrollo
