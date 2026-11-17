"""Comprobación REMOTA de solo lectura del backend real en Render. NO consulta SIGAC ni envía credenciales.

  python backend/scripts/verificar_remoto_real.py --url https://<servicio-real>.onrender.com [--con-token]

Sin token: GET /health, GET /real/cases (debe ser 401 si corre `real_remoto`) y GET /sintetico/casos (404 si ya no
corre el backend sintético). Con `--con-token` pide el token de la app SIN eco y comprueba además GET /real/sesion/estado
y GET /real/cases (solo conteos). Ninguna de esas rutas llega a SIGAC. Imprime solo códigos y conteos.
"""

import argparse
import getpass
import json
import sys
import time

import httpx


def _get(cliente, ruta, token=None, espera=60):
    cabeceras = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        return cliente.get(ruta, headers=cabeceras, timeout=espera)
    except httpx.HTTPError:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verificación remota sin SIGAC del backend real")
    parser.add_argument("--url", required=True, help="URL HTTPS del servicio real (sin valor por defecto)")
    parser.add_argument("--con-token", action="store_true")
    parser.add_argument("--esperar", type=int, default=120, help="segundos máximos para el arranque en frío")
    args = parser.parse_args(argv)
    if not args.url.startswith("https://") or any(c in args.url for c in "?#@ "):
        parser.error("La URL debe ser HTTPS, sin credenciales ni parámetros")
    if args.con_token and not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva para el token")
    informe = {}
    with httpx.Client(base_url=args.url.rstrip("/"), follow_redirects=False, trust_env=False, verify=True) as c:
        limite, r = time.monotonic() + args.esperar, None
        while time.monotonic() < limite:  # arranque en frío del plan gratuito: solo /health, que no toca SIGAC
            r = _get(c, "/health", espera=30)
            if r is not None and r.status_code == 200:
                break
            time.sleep(5)
        informe["health"] = None if r is None else r.status_code
        if r is None or r.status_code != 200:
            print(json.dumps({**informe, "veredicto": "sin_respuesta"}))
            return 1
        cuerpo = r.json() if "json" in r.headers.get("content-type", "") else {}
        informe["health_forma"] = sorted(cuerpo)  # {"status"} = real_remoto; {"estado"} = backend sintético
        informe["real_cases_sin_token"] = getattr(_get(c, "/real/cases"), "status_code", None)
        informe["sintetico_casos_sin_token"] = getattr(_get(c, "/sintetico/casos"), "status_code", None)
        informe["aplicacion"] = ("real_remoto" if informe["real_cases_sin_token"] == 401
                                 and informe["sintetico_casos_sin_token"] == 404 else
                                 "sintetico" if informe["sintetico_casos_sin_token"] == 401 else "desconocida")
        if args.con_token:
            token = getpass.getpass("Token de acceso de la app (sin eco): ")
            estado, casos = _get(c, "/real/sesion/estado", token), _get(c, "/real/cases", token)
            informe["estado_con_token"] = getattr(estado, "status_code", None)
            informe["casos_con_token"] = getattr(casos, "status_code", None)
            if estado is not None and estado.status_code == 403:
                informe["pista"] = "transporte_https_rechazado: revisar TINOTIFY_RR_PROXIES_CONFIABLES"
            if estado is not None and estado.status_code == 200:
                informe["sesion_activa"] = bool(estado.json().get("activa"))
            if casos is not None and casos.status_code == 200:
                informe["expedientes"] = len(casos.json())
            del token
    ok = informe["aplicacion"] == "real_remoto" and (not args.con_token or (
        informe.get("estado_con_token") == 200 and informe.get("expedientes") == 1))
    print(json.dumps({**informe, "veredicto": "ok" if ok else "revisar"}, sort_keys=True))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
