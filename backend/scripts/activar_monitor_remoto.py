"""Guarda tus credenciales SIGAC CIFRADAS en el servidor y, si quieres, lanza la PRIMERA revisión. REQUIERE AUTORIZACIÓN; no se ejecuta sola.

  python backend/scripts/activar_monitor_remoto.py --url https://tinotify.onrender.com [--primera-revision]

1) Comprueba, con GET sin autenticación, que el destino es el backend real. 2) Pide por terminal, SIN eco: token de la app, usuario y
clave SIGAC (y txtCaso con `--pedir-caso-login`) y hace UN `POST /real/sesion` con `recordar: true` (consume 1 de los intentos: lee tu
historial, valida la referencia y guarda las credenciales cifradas; la llave de cifrado solo existe en el servidor). 3) Con
`--primera-revision` pide además el token del MONITOR y hace `POST /real/monitor/ejecutar`: la primera ejecución es línea base
silenciosa (no crea avisos salvo actuaciones posteriores a tu referencia). Imprime solo estados y conteos; nunca credenciales.
"""

import argparse
import getpass
import json
import sys
import time

import httpx

CONFIRMACION = "SIGAC-ACTIVAR-MONITOR"


def es_backend_real(cliente, esperar_s=120):
    limite = time.monotonic() + esperar_s
    while time.monotonic() < limite:  # arranque en frío del plan gratuito
        try:
            r = cliente.get("/health", timeout=30)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    else:
        return False
    try:
        forma = sorted(r.json()) if "json" in r.headers.get("content-type", "") else None
        return (forma == ["status"] and cliente.get("/real/cases", timeout=30).status_code == 401
                and cliente.get("/sintetico/casos", timeout=30).status_code == 404)
    except (httpx.HTTPError, ValueError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guardar credenciales cifradas y lanzar la primera revisión")
    parser.add_argument("--url", required=True)
    parser.add_argument("--pedir-caso-login", action="store_true")
    parser.add_argument("--primera-revision", action="store_true")
    parser.add_argument("--solo-revision", action="store_true",
                        help="no pide credenciales ni inicia sesión: solo lanza la revisión (las credenciales ya están guardadas)")
    args = parser.parse_args(argv)
    if not args.url.startswith("https://") or any(c in args.url for c in "?#@ "):
        parser.error("La URL debe ser HTTPS, sin credenciales ni parámetros")
    if not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
    if input(f"Escribe {CONFIRMACION} para guardar tus credenciales cifradas en {args.url}: ") != CONFIRMACION:
        print("Cancelado sin conexión.")
        return 2
    informe = {}
    with httpx.Client(base_url=args.url.rstrip("/"), follow_redirects=False, trust_env=False, verify=True) as c:
        if not es_backend_real(c):
            print(json.dumps({"error": "el_destino_no_es_el_backend_real_remoto", "credenciales_solicitadas": False}))
            return 5
        if args.solo_revision:
            token_monitor = getpass.getpass("Token del MONITOR (TINOTIFY_RR_MONITOR_TOKEN, sin eco): ").strip()
            try:
                rr = c.post("/real/monitor/ejecutar", headers={"Authorization": f"Bearer {token_monitor}"}, timeout=290)
            except httpx.HTTPError:
                rr = None
            finally:
                del token_monitor
            informe["revision"] = None if rr is None else rr.status_code
            if rr is not None and rr.status_code == 200:
                d = rr.json()
                informe["revision_resultado"] = {k: d.get(k) for k in (
                    "resultado", "expedientes", "novedades", "expedientes_nuevos", "anomalias", "casos_fallidos", "linea_base")}
                informe["avisos_pendientes"] = len(d.get("avisos", []))
            elif rr is not None and rr.status_code == 401:
                informe["significado"] = "token_del_monitor_incorrecto"
            elif rr is not None and rr.status_code == 412:
                informe["significado"] = "no_hay_credenciales_guardadas"
            print(json.dumps(informe, sort_keys=True))
            return 0 if informe.get("revision") == 200 else 3
        token = getpass.getpass("Token de acceso de la app (sin eco): ")
        usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
        clave = getpass.getpass("Clave SIGAC (sin eco): ")
        cuerpo = {"usuario": usuario, "clave": clave, "recordar": True}
        if args.pedir_caso_login:
            cuerpo["caso_login"] = getpass.getpass("txtCaso (sin eco): ")
        cab = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            try:
                r = c.post("/real/sesion", content=json.dumps(cuerpo), headers=cab, timeout=150)
            except httpx.HTTPError:
                print(json.dumps({"login": None, "significado": "sin_respuesta_del_servicio"}))
                return 1
            cuerpo.clear()
            del usuario, clave
            informe["login"] = r.status_code
            if r.status_code == 200:
                datos = r.json()
                informe.update({k: datos.get(k) for k in ("actuaciones", "en_referencia", "adicionales", "credenciales_guardadas")})
            elif r.status_code == 422:
                informe["significado"] = "el_monitor_no_esta_configurado_o_la_lectura_no_corresponde_a_la_referencia"
            c.delete("/real/sesion", headers=cab, timeout=30)  # no dejar el historial temporal en memoria
            if informe.get("credenciales_guardadas") and args.primera_revision:
                token_monitor = getpass.getpass("Token del MONITOR (TINOTIFY_RR_MONITOR_TOKEN, sin eco): ").strip()
                try:
                    rr = c.post("/real/monitor/ejecutar", headers={"Authorization": f"Bearer {token_monitor}"}, timeout=290)
                except httpx.HTTPError:
                    rr = None
                finally:
                    del token_monitor
                informe["revision"] = None if rr is None else rr.status_code
                if rr is not None and rr.status_code == 200:
                    d = rr.json()
                    informe["revision_resultado"] = {k: d.get(k) for k in (
                        "resultado", "expedientes", "novedades", "expedientes_nuevos", "anomalias", "casos_fallidos", "linea_base")}
                    informe["avisos_pendientes"] = len(d.get("avisos", []))
        finally:
            del token
    print(json.dumps(informe, sort_keys=True))
    return 0 if informe.get("credenciales_guardadas") else 3


if __name__ == "__main__":
    raise SystemExit(main())
