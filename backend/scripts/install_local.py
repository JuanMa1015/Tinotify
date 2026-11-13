"""Construye exclusivamente Tinotify local e instala su wheel sin usar la red.

Requiere instalar antes requirements-build.txt con hashes y solo binarios.
Las dependencias de ejecucion/pruebas se instalan por separado.
"""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    pip = [sys.executable, "-m", "pip"]
    with tempfile.TemporaryDirectory(prefix="tinotify-wheel-") as temporal:
        carpeta = Path(temporal)
        subprocess.run([
            *pip, "wheel", "--no-index", "--no-deps", "--no-build-isolation",
            "--only-binary=:all:", "--wheel-dir", str(carpeta), str(backend),
        ], cwd=backend, check=True)
        wheels = list(carpeta.glob("tinotify_backend-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Se esperaba exactamente una wheel local de Tinotify")
        wheel = wheels[0]
        huella = hashlib.sha256(wheel.read_bytes()).hexdigest()
        manifiesto = carpeta/"install-local.txt"
        manifiesto.write_text(
            f"{wheel.as_uri()} --hash=sha256:{huella}\n", encoding="utf-8",
        )
        subprocess.run([
            *pip, "install", "--no-index", "--no-deps", "--force-reinstall", "--require-hashes",
            "--only-binary=:all:", "-r", str(manifiesto),
        ], cwd=backend, check=True)


if __name__ == "__main__":
    main()
