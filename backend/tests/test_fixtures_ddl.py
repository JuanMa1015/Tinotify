"""No cambiar migraciones originales para habilitar fixtures de laboratorio."""

import hashlib
from pathlib import Path

import pytest


MIGRACIONES=Path(__file__).resolve().parents[2]/"supabase/migrations"


@pytest.mark.parametrize("nombre,sha256",[
    ("20261112050000_preparar_esquemas_privados.sql","777b0b12b445a00eb31cd1c54931e35b0f31b8e6d8f81bb23dc9812982e2fba8"),
    ("20261112160000_crear_nucleo_reconciliacion.sql","3f59a91573b872feb5c8bf39032219e08090614f319e9d84e48b8ee5248e9324"),
    ("20261114010000_habilitar_persistencia_sintetica.sql","ddecca3d86606712d670a2f4690f8e852966fec4b96b00a76646c5376a091ae8"),
])
def test_migraciones_originales_sin_cambios(nombre,sha256):
    assert hashlib.sha256((MIGRACIONES/nombre).read_bytes().replace(b"\r\n",b"\n")).hexdigest()==sha256
