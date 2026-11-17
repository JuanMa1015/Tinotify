"""ÚNICA prueba de autenticación real desde Render. REQUIERE AUTORIZACIÓN EXPLÍCITA; no se ejecuta sola.

  python backend/scripts/prueba_login_remoto.py --url https://<servicio-real>.onrender.com

`--url` es obligatorio (no hay valor por defecto) para no enviar nunca credenciales al servicio sintético por error. Antes de
pedir credenciales comprueba, solo con GET sin autenticación y sin SIGAC, que el destino ES el backend real remoto
(`/health` con clave `status`, `/real/cases` → 401 y `/sintetico/casos` → 404); si no, aborta sin pedir nada.
Luego hace un solo `POST /real/sesion` (los servidores no reintentan; este script tampoco), cuenta el historial y cierra la
sesión con `DELETE /real/sesion`. Pide por terminal, SIN eco: token de la app, usuario y clave SIGAC (y txtCaso con
`--pedir-caso-login`). Las credenciales viajan solo por HTTPS en el cuerpo del POST y no se escriben en disco ni se
imprimen. Imprime únicamente estados HTTP y conteos. Consume 1 de los 3 intentos del presupuesto del servidor.
Antes: `verificar_remoto_real.py --url ...` debe dar veredicto «ok».
"""

import argparse
import getpass
import json
import sys
import time

import httpx

CONFIRMACION = "SIGAC-LOGIN-REMOTO"
SIGNIFICADO = {
    200: "acceso_y_lectura_correctos", 401: "token_de_la_app_invalido", 403: "SIGAC_no_confirmo_el_acceso_o_transporte_rechazado",
    409: "ya_hay_un_acceso_en_curso", 413: "cuerpo_demasiado_grande", 422: "la_lectura_no_corresponde_a_la_referencia",
    429: "presupuesto_de_intentos_agotado", 502: "SIGAC_no_respondio_como_se_esperaba_o_no_es_alcanzable",
    503: "servicio_no_configurado",
}


def es_backend_real(cliente, esperar_s=120):
    """True solo si el destino es `real_remoto`. Usa únicamente GET sin autenticación; no toca SIGAC."""
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
        casos = cliente.get("/real/cases", timeout=30).status_code
        sintetico = cliente.get("/sintetico/casos", timeout=30).status_code
    except (httpx.HTTPError, ValueError):
        return False
    return forma == ["status"] and casos == 401 and sintetico == 404


def main(argv=None):
    parser = argparse.ArgumentParser(description="Única prueba de login SIGAC desde Render")
    parser.add_argument("--url", required=True)
    parser.add_argument("--pedir-caso-login", action="store_true")
    args = parser.parse_args(argv)
    if not args.url.startswith("https://") or any(c in args.url for c in "?#@ "):
        parser.error("La URL debe ser HTTPS, sin credenciales ni parámetros")
    if not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
    if input(f"Escribe {CONFIRMACION} para autorizar UN login SIGAC desde {args.url}: ") != CONFIRMACION:
        print("Cancelado sin conexión.")
        return 2
    informe = {}
    with httpx.Client(base_url=args.url.rstrip("/"), follow_redirects=False, trust_env=False, verify=True) as c:
        if not es_backend_real(c):
            print(json.dumps({"error": "el_destino_no_es_el_backend_real_remoto", "credenciales_solicitadas": False}))
            return 5
        token = getpass.getpass("Token de acceso de la app (sin eco): ")
        usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
        clave = getpass.getpass("Clave SIGAC (sin eco): ")
        cuerpo = {"usuario": usuario, "clave": clave}
        if args.pedir_caso_login:
            cuerpo["caso_login"] = getpass.getpass("txtCaso (sin eco): ")
        cabeceras = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            inicio = time.monotonic()
            try:
                r = c.post("/real/sesion", content=json.dumps(cuerpo), headers=cabeceras, timeout=150)
            except httpx.HTTPError:
                print(json.dumps({"login": None, "significado": "sin_respuesta_del_servicio"}))
                return 1
            cuerpo.clear()
            del usuario, clave  # las credenciales no se necesitan más
            informe["login"] = r.status_code
            informe["significado"] = SIGNIFICADO.get(r.status_code, "respuesta_no_prevista")
            informe["segundos"] = round(time.monotonic() - inicio, 1)
            if r.status_code == 200:
                datos = r.json()
                informe.update({k: datos.get(k) for k in ("actuaciones", "en_referencia", "adicionales", "expira_en_s")})
                caso = c.get("/real/cases", headers=cabeceras, timeout=30).json()[0]["id"]
                lista = c.get(f"/real/cases/{caso}/historial", headers=cabeceras, timeout=60)
                if lista.status_code == 200:
                    informe["historial"] = {k: lista.json().get(k) for k in ("total", "en_referencia", "formato_inesperado")}
            c.delete("/real/sesion", headers=cabeceras, timeout=30)  # siempre: no dejar contenido en memoria
            informe["cierre"] = "solicitado"
        finally:
            del token
    print(json.dumps(informe, sort_keys=True))
    return 0 if informe.get("login") == 200 else 3


if __name__ == "__main__":
    raise SystemExit(main())
