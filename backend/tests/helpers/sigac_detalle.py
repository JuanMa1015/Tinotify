"""Envoltura de endpoint enteramente sintética; no es fixture del parser genérico."""


def detalle(contenido, numero="101", *, cabecera=None, oculto=None, estado="En proceso"):
    # Los llamadores pueden suministrar un documento histórico o un fragmento.
    contenido = contenido.removeprefix("<html><body>").removesuffix("</body></html>")
    cabecera = numero if cabecera is None else cabecera
    oculto = numero if oculto is None else oculto
    return (
        '<html><body><div class="ui-widget-content ui-corner-all">'
        f'<div class="ui-state-default ui-corner-all">Información del caso Nro.{cabecera} - {estado}</div>'
        '<form name="form1" id="form1" action="casos.guardarCaso.con" method="post" '
        'enctype="multipart/form-data">'
        f'<input name="hidCaso" id="hidCaso" type="hidden" value="{oculto}">'
        f'{contenido}</form></div></body></html>'
    )
