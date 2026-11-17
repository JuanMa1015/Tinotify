"""Verificador (solo lectura, sin red) de lo que contendría la rama `deploy/real-remoto`. No crea ramas ni commits.

  python backend/scripts/verificar_rama_despliegue.py [--listar] [--base origin/main] [--local backend/.local]

Toma exactamente los archivos que Git consideraría (`git ls-files -co --exclude-standard`), los restringe al conjunto de
despliegue (MANIFIESTO) y comprueba que NO contenga: rutas sensibles (.local, SQLite, APK, almacenes de claves, google-services,
archivos de acreditación/referencia/código de acceso, .env), secretos conocidos de este equipo (clave de acreditación, código de
acceso, MAC y huellas de la referencia, identificadores de v2, número de caso), claves privadas, URLs con contraseña, ni
fragmentos de texto judicial real tomados del almacén v1 (solo lectura inmutable). Imprime únicamente conteos y las rutas
infractoras (nunca el contenido). Código de salida 0 si no hay infracciones.
"""

import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

# Qué entra en la rama: el backend, su documentación, la configuración de ignorados y la definición del servicio.
# Todo lo demás (mobile/, supabase/, etc.) lo hereda la rama base sin cambios o no se despliega.
MANIFIESTO = ("backend/", "docs/", ".gitignore", "pytest.ini", "render.yaml", "render.real-remoto.propuesta.yaml")
# En la rama, `render.real-remoto.propuesta.yaml` pasa a ser `render.yaml` (documentación de la configuración del servicio).
RUTAS_PROHIBIDAS = re.compile(
    r"(^|/)(\.local|\.venv|venv|node_modules|\.expo|exportaciones|build|dist|__pycache__|android|ios)/"
    r"|\.(sqlite|sqlite3|db|apk|aab|keystore|jks|pem|key|p12|pfx|crt|cer)(-\w+)?$"
    r"|(^|/)google-services\.json$|(^|/)acreditacion_sigac|(^|/)referencia_portable(?!\.py$)|(^|/)codigo_acceso_real"
    r"|(^|/)\.env($|\.(?!example$))|(^|/)credentials|service-account|(^|/)cookies|storage_state", re.IGNORECASE)
PATRONES_SECRETOS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@/]+@"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),   # JWT (claves de Supabase)
    re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}"),
)
MAX_BYTES = 2_000_000


def pertenece(ruta):
    return any(ruta == m or (m.endswith("/") and ruta.startswith(m)) for m in MANIFIESTO)


def evaluar(archivos, leer, secretos=(), fragmentos=()):
    """`archivos`: rutas relativas; `leer(ruta)` -> bytes. Devuelve {categoría: [rutas]} (vacío si todo está bien)."""
    problemas = {"ruta_prohibida": [], "demasiado_grande": [], "secreto_conocido": [], "patron_de_secreto": [],
                 "texto_judicial": [], "ilegible": []}
    for ruta in archivos:
        if RUTAS_PROHIBIDAS.search(ruta):
            problemas["ruta_prohibida"].append(ruta)
            continue
        try:
            datos = leer(ruta)
        except OSError:
            problemas["ilegible"].append(ruta)
            continue
        if len(datos) > MAX_BYTES:
            problemas["demasiado_grande"].append(ruta)
            continue
        texto = datos.decode("utf-8", "ignore")
        if any(s in texto for s in secretos):
            problemas["secreto_conocido"].append(ruta)
        if any(p.search(texto) for p in PATRONES_SECRETOS):
            problemas["patron_de_secreto"].append(ruta)
        if any(f in texto for f in fragmentos):
            problemas["texto_judicial"].append(ruta)
    return {k: sorted(v) for k, v in problemas.items() if v}


def secretos_locales(raiz, local=None):
    """Valores sensibles de este equipo, solo en memoria. Si faltan los archivos locales, no se comprueban."""
    valores = set()
    local = Path(local) if local else raiz / "backend" / ".local"
    try:
        clave = json.loads((local / "acreditacion_sigac.json").read_text(encoding="utf-8"))["clave_hex"]
        valores.update({clave})
    except (OSError, ValueError, KeyError):
        pass
    try:
        valores.add((local / "codigo_acceso_real.txt").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    try:
        ref = json.loads((local / "referencia_portable.json").read_text(encoding="utf-8"))
        valores.update({ref["mac"], ref["caso_id"], ref["huellas"][0]})
        valores.add(f'"numero":{ref["numero"]}')
        valores.add(f'"numero": {ref["numero"]}')
    except (OSError, ValueError, KeyError, IndexError):
        pass
    try:
        con = sqlite3.connect(f"{(local / 'real_v2.sqlite3').resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            valores.add(con.execute("SELECT caso FROM expedientes").fetchone()[0])
            valores.add(con.execute("SELECT version_hash FROM actuaciones LIMIT 1").fetchone()[0])
        finally:
            con.close()
    except (OSError, sqlite3.Error, TypeError):
        pass
    return {v for v in valores if isinstance(v, str) and len(v) >= 8}


def fragmentos_judiciales(raiz, maximo=1500, local=None):
    """Líneas largas del texto judicial real de v1 (solo lectura inmutable) para comprobar que no está en la rama."""
    ruta = (Path(local) if local else raiz / "backend" / ".local") / "real.sqlite3"
    fragmentos = set()
    try:
        con = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            for (contenido,) in con.execute("SELECT contenido FROM vista_actuaciones"):
                for linea in re.split(r"[\n\\]+", contenido or ""):
                    linea = linea.strip(" \"',:{}[]")
                    if len(linea) >= 40:
                        fragmentos.add(linea)
                        if len(fragmentos) >= maximo:
                            return fragmentos
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        pass
    return fragmentos


def _git(raiz, *args):
    return subprocess.run(["git", *args], cwd=raiz, capture_output=True, text=True, check=True).stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verifica el contenido previsto de la rama de despliegue (sin crear nada)")
    parser.add_argument("--listar", action="store_true", help="imprime las rutas incluidas (no su contenido)")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--local", type=Path, help="carpeta `.local` con los secretos de este equipo (por defecto <raiz>/backend/.local)")
    args = parser.parse_args(argv)
    raiz = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    candidatos = [r for r in _git(raiz, "ls-files", "-co", "--exclude-standard").splitlines() if r]
    incluidos = sorted(r for r in candidatos if pertenece(r))
    excluidos_sensibles = [r for r in candidatos if RUTAS_PROHIBIDAS.search(r) and not pertenece(r)]
    secretos, fragmentos = secretos_locales(raiz, args.local), fragmentos_judiciales(raiz, local=args.local)
    problemas = evaluar(incluidos, lambda r: (raiz / r).read_bytes(), secretos, fragmentos)
    # Comparación con la rama base: qué sería nuevo o modificado (solo conteos).
    try:
        base = {}
        for linea in _git(raiz, "ls-tree", "-r", args.base).splitlines():
            cabecera, ruta = linea.split("	", 1)
            base[ruta] = cabecera.split()[2]
        nuevos = modificados = iguales = 0
        for r in incluidos:
            blob = subprocess.run(["git", "hash-object", r], cwd=raiz, capture_output=True, text=True).stdout.strip()
            destino = "render.yaml" if r == "render.real-remoto.propuesta.yaml" else r
            if destino not in base:
                nuevos += 1
            elif base[destino] != blob:
                modificados += 1
            else:
                iguales += 1
        comparacion = {"nuevos": nuevos, "modificados": modificados, "iguales": iguales}
    except subprocess.CalledProcessError:
        comparacion = "base_no_disponible"
    informe = {
        "archivos_candidatos": len(candidatos), "archivos_en_la_rama": len(incluidos),
        "fuera_del_manifiesto": len(candidatos) - len(incluidos),
        "con_ruta_sensible_fuera_del_manifiesto": len(excluidos_sensibles),
        "secretos_locales_comprobados": len(secretos), "fragmentos_judiciales_comprobados": len(fragmentos),
        "frente_a_la_base": comparacion, "problemas": problemas, "veredicto": "limpio" if not problemas else "BLOQUEADO",
    }
    if args.listar:
        informe["rutas"] = incluidos
    print(json.dumps(informe, ensure_ascii=False, sort_keys=True, indent=1))
    return 0 if not problemas else 4


if __name__ == "__main__":
    sys.exit(main())
