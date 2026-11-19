"""Plantillas de los correos de Tinotify: asunto, texto plano y HTML con estilos en línea (los clientes de correo no cargan hojas de estilo).

Todo en español y marcado como tal (`lang="es"`), para que los clientes no ofrezcan «traducir». Sin imágenes externas ni rastreadores.
"""

import html

MARINO, LIMA, FONDO, TEXTO_SUAVE, CAJA = "#14213D", "#A8D83F", "#D9E4F5", "#52627C", "#EEF3FB"


def _marco(titulo, previa, cuerpo, pie):
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta http-equiv="Content-Language" content="es"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title></head>
<body style="margin:0;padding:0;background:{FONDO};font-family:Arial,Helvetica,sans-serif;color:{MARINO}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{FONDO}">{html.escape(previa)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{FONDO};padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:16px;overflow:hidden">
<tr><td style="background:{MARINO};padding:20px 28px"><span style="font-size:24px;font-weight:700;color:{LIMA};letter-spacing:.5px">Tinotify</span></td></tr>
<tr><td style="padding:28px 28px 8px">{cuerpo}</td></tr>
<tr><td style="padding:8px 28px 28px;font-size:12px;line-height:18px;color:{TEXTO_SUAVE}">{pie}</td></tr>
</table></td></tr></table></body></html>"""


def correo_codigo(codigo: str, motivo: str, vigencia: str):
    """(asunto, texto, html) del correo con el código de un solo uso. `motivo`: «crear tu cuenta» o «entrar a tu cuenta»."""
    asunto = f"{codigo} es tu código de Tinotify"
    aviso = "Si no lo pediste, ignora este mensaje: nadie entra a tu cuenta sin este código. Tinotify nunca te lo pedirá por teléfono ni por mensaje."
    texto = (f"Tu código para {motivo}: {codigo}\n\nEscríbelo en la aplicación de Tinotify. Vale {vigencia} y solo sirve una vez.\n\n{aviso}")
    cuerpo = (f"<p style='margin:0 0 6px;font-size:16px;line-height:24px'>Tu código para {html.escape(motivo)}:</p>"
              f"<p style='margin:14px 0;padding:18px 0;text-align:center;background:{CAJA};border-radius:12px;font-size:38px;font-weight:700;"
              f"letter-spacing:10px;font-family:Consolas,Menlo,monospace;color:{MARINO}'>{html.escape(codigo)}</p>"
              f"<p style='margin:0 0 14px;font-size:15px;line-height:22px'>Escríbelo en la aplicación de Tinotify. Vale <strong>{html.escape(vigencia)}</strong> y solo sirve una vez.</p>")
    return asunto, texto, _marco(asunto, f"Tu código es {codigo}. Vale {vigencia}.", cuerpo, html.escape(aviso))


def correo_prueba():
    """(asunto, texto, html) del correo de prueba del propietario."""
    asunto = "Prueba de correo de Tinotify"
    texto = "El correo de Tinotify funciona: si ves este mensaje, la aplicación puede enviar códigos de acceso."
    cuerpo = (f"<p style='margin:0 0 10px;font-size:20px;font-weight:700'>✓ El correo funciona</p>"
              "<p style='margin:0 0 14px;font-size:15px;line-height:22px'>Si ves este mensaje, Tinotify puede enviar códigos de acceso a tus usuarios.</p>")
    return asunto, texto, _marco(asunto, "El correo de Tinotify funciona.", cuerpo, "Mensaje de prueba: no requiere ninguna acción.")
