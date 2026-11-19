"""Cliente de correo falso para las pruebas: guarda lo que se enviaría y deja leer el código."""

import re


class CorreoFalso:
    def __init__(self, motivo=None):
        self.enviados, self.motivo = [], motivo   # motivo None = el proveedor acepta el envío

    def enviar(self, destino, asunto, texto, html):
        self.enviados.append({"destino": destino, "asunto": asunto, "texto": texto, "html": html})
        return self.motivo

    def enviar_prueba(self):
        return self.enviar("remitente@ejemplo.com", "prueba", "t", "h")

    def codigo(self, i=-1):
        return re.search(r"\b\d{6}\b", self.enviados[i]["texto"]).group()
