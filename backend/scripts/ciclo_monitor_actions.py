"""Ciclo del monitor para GitHub Actions: revisa, envía el correo de cada aviso pendiente y lo confirma.

Variables de entorno (secretos de GitHub, nunca en el repositorio):
  TINOTIFY_URL, TINOTIFY_MONITOR_TOKEN           obligatorias
  TINOTIFY_CORREO_ACTIVO=1                       sin esto NO se envía correo y los avisos quedan pendientes
  TINOTIFY_CORREO_DESTINO, TINOTIFY_SMTP_USUARIO, TINOTIFY_SMTP_CLAVE   (Gmail: contraseña de aplicación)

El registro público solo dice «ok» o un código de fallo: ningún conteo ni dato del expediente. El correo lleva solo conteos.
Un aviso se confirma como entregado únicamente tras enviar el correo (entrega al menos una vez).
"""

from email.message import EmailMessage
import html
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


URL_SIGAC = "https://sigac.udea.edu.co/sigac/"


def _resumen(aviso):
    partes = []
    if aviso.get("novedades"):
        partes.append(f"{aviso['novedades']} actuación(es) nueva(s) en {aviso['expedientes_con_novedades']} expediente(s)")
    if aviso.get("expedientes_nuevos"):
        partes.append(f"{aviso['expedientes_nuevos']} expediente(s) nuevo(s) en tu cuenta")
    if aviso.get("anomalias"):
        partes.append(f"{aviso['anomalias']} lectura(s) a revisar")
    return "; ".join(partes).capitalize() + "."


def _linea(x):
    base = f"Radicado {x['numero']} — {x['cliente']}"
    if x.get("nuevo"):
        return f"{base}: expediente nuevo"
    n = x.get("novedades") or 0
    return f"{base}: {n} actuación(es) nueva(s)" if n else base


def _detalles(aviso, numero):
    """Una línea por actuación nueva sin ver del expediente: etapa, sentido y fecha (nunca el texto de la actuación)."""
    salida = []
    for d in aviso.get("novedades_detalle") or []:
        if d.get("numero") != numero or not d.get("etapa"):
            continue
        sentido = f" ({d['origen']} → {d['destino']})" if d.get("origen") and d.get("destino") else ""
        salida.append(f"{d['etapa']}{sentido}" + (f" · {d['fecha'][:10]}" if d.get("fecha") else ""))
    return salida[:5]


def construir_correo(aviso, origen, destino, url_app=None):
    """Correo con el detalle (radicado y nombre de cada expediente con novedades) y dos botones: SIGAC y la app. El correo va al propio
    buzón del usuario; el contenido de las actuaciones nunca se incluye."""
    expedientes = aviso.get("expedientes") or []
    mensaje = EmailMessage()
    mensaje["Subject"], mensaje["From"], mensaje["To"] = "Tinotify: hay novedades en SIGAC", origen, destino
    lineas = [_linea(x) for x in expedientes]
    subs = [_detalles(aviso, x["numero"]) for x in expedientes]
    texto = _resumen(aviso) + ("\n\n" + "\n".join("• " + l + "".join("\n    – " + d for d in sub) for l, sub in zip(lineas, subs)) if lineas else "")
    texto += f"\n\nIr a SIGAC: {URL_SIGAC}" + (f"\nAbrir Tinotify: {url_app}" if url_app else "")
    texto += "\n\nTinotify no está afiliado a SIGAC. Confirma siempre en el sistema oficial."
    mensaje.set_content(texto)
    items = "".join(f"<li>{html.escape(l)}" + "".join(f"<br><span style='color:#52627C;font-size:14px'>– {html.escape(d)}</span>" for d in sub) + "</li>"
                    for l, sub in zip(lineas, subs))
    boton = "display:inline-block;padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:700;margin:6px 8px 6px 0;"
    cuerpo = (f"<div style='font-family:Arial,sans-serif;color:#14213D;max-width:520px'><h2 style='margin:0 0 8px'>Tinotify</h2>"
              f"<p style='font-size:16px'>{html.escape(_resumen(aviso))}</p>" + (f"<ul style='font-size:15px;line-height:1.6'>{items}</ul>" if items else "") +
              f"<p><a href='{URL_SIGAC}' style='{boton}background:#14213D;color:#fff'>Ir a SIGAC</a>" +
              (f"<a href='{html.escape(url_app)}' style='{boton}background:#A8D83F;color:#14213D'>Abrir Tinotify</a>" if url_app else "") + "</p>"
              "<p style='font-size:12px;color:#52627C'>Tinotify no está afiliado a SIGAC. Confirma siempre en el sistema oficial.</p></div>")
    mensaje.add_alternative(cuerpo, subtype="html")
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
                enviar(construir_correo(aviso, usuario, destino, url.rstrip('/') + '/abrir'), usuario, clave)
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
