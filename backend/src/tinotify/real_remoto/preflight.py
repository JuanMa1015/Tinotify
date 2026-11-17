"""Comprobación de arranque SIN red y SIN SIGAC: ¿cargaría el servicio con este entorno y estos archivos?

Construye la aplicación exactamente como `crear_app` (configuración, clave de acreditación, referencia portable,
contrato y expediente acreditado). Devuelve solo booleanos, conteos y códigos estables: nunca contenido de los
archivos, valores de variables ni identificadores. Se usa en local con los mismos archivos que se subirán como
Secret Files y no abre conexiones.
"""

from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.real_remoto.app import crear_app
from tinotify.real_remoto.config import Config, ConfiguracionInsegura, VariablesAjenas
from tinotify.services import referencia_portable
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada
from tinotify.services.politica_real_local import cargar_clave_acreditacion, politica_desde_clave


def verificar(entorno):
    resultado = {"configuracion": False, "clave_acreditacion": False, "referencia_portable": False,
                 "expediente_acreditado": False, "aplicacion": False}
    try:
        config = Config.desde_entorno(entorno)
        resultado["configuracion"] = True
    except VariablesAjenas as error:
        return {**resultado, "fallo": error.codigo, "variables_a_retirar": list(error.nombres)}
    except ConfiguracionInsegura as error:
        return {**resultado, "fallo": error.codigo}
    try:
        clave = cargar_clave_acreditacion(config.acreditacion)
        resultado["clave_acreditacion"] = True
        referencia = referencia_portable.cargar(config.referencia, clave, instancia=INSTANCIA_REAL)
        resultado["referencia_portable"] = True
        resultado["huellas"] = len(referencia.entradas())
        politica_desde_clave(clave).exigir_expediente(referencia.numero, INSTANCIA_REAL)
        resultado["expediente_acreditado"] = True
        crear_app(config)
        resultado["aplicacion"] = True
    except IdentidadExpedienteNoVerificada:
        resultado["fallo"] = "clave_o_expediente_no_acreditado"
    except referencia_portable.ReferenciaPortableInvalida:
        resultado["fallo"] = "referencia_portable_invalida"
    except ConfiguracionInsegura as error:
        resultado["fallo"] = error.codigo
    except Exception as error:  # nunca el mensaje: podría contener rutas
        resultado["fallo"] = f"error_inesperado_{type(error).__name__}"
    return resultado
