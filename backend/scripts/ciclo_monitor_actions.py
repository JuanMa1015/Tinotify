"""Ciclo del monitor para GitHub Actions: revisa, envía el correo de cada aviso pendiente y lo confirma.

Variables de entorno (secretos de GitHub, nunca en el repositorio):
  TINOTIFY_URL, TINOTIFY_MONITOR_TOKEN           obligatorias
  TINOTIFY_CORREO_ACTIVO=1                       sin esto NO se envía correo y los avisos quedan pendientes
  TINOTIFY_CORREO_DESTINO, TINOTIFY_SMTP_USUARIO, TINOTIFY_SMTP_CLAVE   (Gmail: contraseña de aplicación)

El registro público solo dice «ok» o un código de fallo: ningún conteo ni dato del expediente. El correo lleva solo conteos.
Un aviso se confirma como entregado únicamente tras enviar el correo (entrega al menos una vez).
"""

from email.message import EmailMessage
import os
import smtplib
import sys
import time

import httpx

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465


def _esperar_servicio(c, esperar_s=180):
    limite = time.monotonic() + esperar_s
    while time.monotonic() < limite:  # arranque en frío del plan gratuito
        try:
            if c.get("/health", timeout=30).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(5)
    return False


def _revisar_todos(c, cabeceras):
    """Revisa al propietario y, uno por uno, a cada usuario con credenciales. Un fallo no detiene a los demás. Devuelve los fallos.

    Nunca se imprimen identificadores de usuario ni conteos: el registro de Actions es público."""
    fallos = 0
    try:
        r = c.post("/real/monitor/ejecutar", headers=cabeceras, timeout=290)
        if r.status_code not in (200, 412):  # 412: el propietario no tiene credenciales guardadas (no es un fallo)
            print(f"fallo: revision_http_{r.status_code}")
            fallos += 1
    except httpx.HTTPError:
        print("fallo: revision_sin_respuesta")
        fallos += 1
    try:
        u = c.get("/real/monitor/usuarios", headers=cabeceras, timeout=60)
    except httpx.HTTPError:
        u = None
    if u is None or u.status_code != 200:
        if u is not None and u.status_code != 404:
            print(f"fallo: usuarios_http_{u.status_code}")
            fallos += 1
        return fallos
    for usuario in u.json().get("usuarios", []):
        try:
            r = c.post("/real/monitor/ejecutar", params={"usuario": usuario}, headers=cabeceras, timeout=290)
            if r.status_code != 200:
                print(f"fallo: revision_usuario_http_{r.status_code}")
                fallos += 1
        except httpx.HTTPError:
            print("fallo: revision_usuario_sin_respuesta")
            fallos += 1
    return fallos


def _informar(c, cabeceras, aviso, estado):
    """Dice al servidor cómo salió el correo de este aviso (la app lo muestra). Nunca interrumpe el ciclo."""
    try:
        c.post(f"/real/monitor/avisos/{aviso['id']}/canal", headers=cabeceras, json={"canal": "correo", "estado": estado}, timeout=30)
    except httpx.HTTPError:
        pass


def construir_correo(aviso, origen, destino):
    partes = []
    if aviso.get("novedades"):
        partes.append(f"{aviso['novedades']} actuación(es) nueva(s) en {aviso['expedientes_con_novedades']} expediente(s)")
    if aviso.get("expedientes_nuevos"):
        partes.append(f"{aviso['expedientes_nuevos']} expediente(s) nuevo(s) en tu cuenta")
    if aviso.get("anomalias"):
        partes.append(f"{aviso['anomalias']} lectura(s) a revisar")
    mensaje = EmailMessage()
    mensaje["Subject"], mensaje["From"], mensaje["To"] = "Tinotify: hay novedades en SIGAC", origen, destino
    mensaje.set_content("; ".join(partes).capitalize() + ".\n\nEntra a SIGAC para ver el detalle. Este aviso no incluye datos del caso.")
    return mensaje


def enviar_correo(mensaje, usuario, clave):
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.login(usuario, clave)
        smtp.send_message(mensaje)


def main(entorno=None, enviar=enviar_correo, cliente=None):
    env = os.environ if entorno is None else entorno
    url, token = env.get("TINOTIFY_URL", "").strip(), env.get("TINOTIFY_MONITOR_TOKEN", "").strip()
    if not url.startswith("https://") or not token:
        print("fallo: configuracion_incompleta")
        return 2
    cabeceras = {"Authorization": f"Bearer {token}"}
    propio = cliente is None
    c = cliente or httpx.Client(base_url=url.rstrip("/"), follow_redirects=False, trust_env=False, verify=True)
    try:
        if not _esperar_servicio(c):
            print("fallo: servicio_sin_respuesta")
            return 3
        fallos = _revisar_todos(c, cabeceras)
        a = c.get("/real/monitor/avisos", headers=cabeceras, timeout=60)
        if a.status_code != 200:
            print(f"fallo: avisos_http_{a.status_code}")
            return 3
        avisos = a.json().get("avisos", [])
        if not avisos:
            print("ok: sin_avisos" if not fallos else "fallo: revisiones_con_errores")
            return 0 if not fallos else 3
        if env.get("TINOTIFY_CORREO_ACTIVO") != "1":
            for aviso in avisos:
                _informar(c, cabeceras, aviso, "desactivado")
            print("ok: avisos_pendientes_correo_desactivado" if not fallos else "fallo: revisiones_con_errores")
            return 0 if not fallos else 3
        destino_propietario, usuario, clave = (env.get(k, "").strip() for k in
                                               ("TINOTIFY_CORREO_DESTINO", "TINOTIFY_SMTP_USUARIO", "TINOTIFY_SMTP_CLAVE"))
        if not (usuario and clave):
            print("fallo: correo_sin_configurar")
            return 2
        envio_fallido = False
        for aviso in avisos:
            # Un usuario: SU correo. El correo del propietario (secreto) es solo para los avisos del propietario: jamás para los de otro.
            destino = aviso.get("destino") or (None if aviso.get("usuario") else destino_propietario)
            if not destino:
                _informar(c, cabeceras, aviso, "desactivado")  # sin correo de aviso: solo recibe la notificación del teléfono
                if aviso.get("usuario"):
                    c.post(f"/real/monitor/avisos/{aviso['id']}/entregado", headers=cabeceras, timeout=60)  # nada más que hacer por correo
                continue
            try:
                enviar(construir_correo(aviso, usuario, destino), usuario, clave)
            except (OSError, smtplib.SMTPException):
                _informar(c, cabeceras, aviso, "fallido")
                envio_fallido = True  # sin confirmar: el aviso sigue pendiente y se reintenta en la próxima ejecución
                continue
            _informar(c, cabeceras, aviso, "enviado")
            e = c.post(f"/real/monitor/avisos/{aviso['id']}/entregado", headers=cabeceras, timeout=60)
            if e.status_code not in (200, 404):
                print(f"fallo: confirmacion_http_{e.status_code}")
                return 3
        if envio_fallido:
            print("fallo: envio_de_correo")
            return 4
        print("ok: avisos_enviados" if not fallos else "fallo: revisiones_con_errores")
        return 0 if not fallos else 3
    finally:
        if propio:
            c.close()


if __name__ == "__main__":
    sys.exit(main())
