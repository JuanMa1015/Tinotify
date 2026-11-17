"""Salida diagnóstica cerrada: códigos constantes y conteos, nunca datos DOM."""

from enum import Enum


class CodigoHistorial(str, Enum):
    NO_CLASIFICADO = "fallo_no_clasificado"
    ERROR_INTERNO = "error_interno"
    ADVERTENCIA_BIBLIOTECA = "advertencia_biblioteca"
    LECTURA_ESTABLE = "lectura_estable"
    LECTURA_CON_CAMBIOS = "lectura_con_cambios"
    ENTRADA_INVALIDA = "entrada_ensayo_invalida"
    ACCESO_INCOMPLETO = "entrada_acceso_incompleta"
    AUTENTICACION_NO_CONFIRMADA = "autenticacion_no_confirmada"
    TIPO_NO_OFRECIDO = "tipo_acceso_no_ofrecido"
    REDIRECCION_NO_CONFIRMADA = "redireccion_no_confirmada"
    LOCATION_AUSENTE = "location_ausente"
    LOCATION_MULTIPLE = "location_multiple"
    REDIRECCION_FORMATO = "redireccion_formato_no_admitido"
    REDIRECCION_ORIGEN = "redireccion_origen_no_admitido"
    REDIRECCION_ACCESO = "redireccion_a_acceso"
    REDIRECCION_DESTINO = "redireccion_destino_no_confirmado"
    HTTP_INESPERADO = "respuesta_http_inesperada"
    ROL_RESPUESTA_INVALIDA = "rol_respuesta_no_confirmada"
    ROL_NO_OFRECIDO = "rol_estudiante_no_ofrecido"
    ROL_ACCION_INVALIDA = "rol_accion_no_confirmada"
    FORMULARIO_AMBIGUO = "formulario_ausente_o_ambiguo"
    FORMULARIO_METODO_INVALIDO = "formulario_metodo_o_codificacion_no_confirmados"
    FORMULARIO_CAMPOS_INVALIDOS = "formulario_campos_no_confirmados"
    FORMULARIO_CONTROLES_INVALIDOS = "formulario_controles_no_confirmados"
    FORMULARIO_DUPLICADO = "formulario_campos_duplicados"
    FORMULARIO_SELECTOR_INVALIDO = "formulario_selector_no_confirmado"
    FORMULARIO_OPCIONES_INVALIDAS = "formulario_opciones_no_confirmadas"
    FORMULARIO_SUBMIT_SIN_VALOR = "formulario_submit_sin_valor"
    LISTADO_NO_CONFIRMADO = "listado_no_confirmado"
    LISTADO_CAMBIADO = "listado_cambiado_entre_lecturas"
    EXPEDIENTE_NO_LISTADO = "expediente_no_listado"
    IDENTIDAD_DETALLE_NO_CONFIRMADA = "consistencia_identidad_detalle_no_confirmada"
    HISTORIAL_FUERA_DETALLE = "historial_fuera_detalle_o_ambito_ambiguo"
    BASELINE_INVALIDO = "baseline_con_eventos_inesperados"
    DOCUMENTO_INCOMPLETO = "documento_incompleto"
    PAGINA_NO_PROTEGIDA = "pagina_no_protegida"
    SIN_ACTUACIONES = "sin_actuaciones_reconocidas"
    TOTAL_DISCORDANTE = "total_actuaciones_discordante"
    CABECERAS_DISCORDANTES = "actuaciones_cabeceras_discordantes"
    CONTENEDOR_INVALIDO = "contenedor_invalido"
    CONTENEDOR_AUSENTE = "contenedor_ausente"
    CONTENEDOR_DUPLICADO = "contenedor_duplicado"
    CONTENEDOR_ANEXOS = "contenedor_es_anexo"
    CONTENEDOR_SIN_TABLAS = "contenedor_sin_tablas"
    AMBITO_NO_VERIFICADO = "ambito_tablas_no_interpretadas"
    ANTES_DEL_SEPARADOR = "historial_antes_del_primer_separador"
    BLOQUE_CON_CONTROLES = "actuacion_con_controles"
    CABECERA_INVALIDA = "actuacion_cabecera_no_interpretable"
    FECHA_INVALIDA = "actuacion_formato_fecha_invalido"
    RESPONSABLE_AUSENTE = "actuacion_responsable_ausente"
    TITULO_INVALIDO = "actuacion_cabecera_opcional_invalida"
    COMUNICACION_INVALIDA = "actuacion_comunicacion_invalida"
    FILA_INVALIDA = "actuacion_fila_no_interpretable"
    ETIQUETA_INVALIDA = "actuacion_etiqueta_no_interpretable"
    SEPARADOR_AUSENTE = "actuacion_separador_ausente"
    SIN_CONTENIDO = "actuacion_sin_filas_contenido"
    ANEXOS_ANIDADOS = "anexos_anidados_no_admitidos"
    ANEXO_FILA_INVALIDA = "anexo_fila_no_interpretable"
    ANEXO_ENLACE_AUSENTE = "anexo_enlace_ausente"
    ANEXO_ENLACES_MULTIPLES = "anexo_enlaces_multiples"
    ANEXO_REFERENCIA_INVALIDA = "anexo_referencia_no_admitida"
    ANEXOS_CONTENIDO_INVALIDO = "anexos_contenido_no_interpretable"
    SESION_NO_CONFIRMADA = "sesion_no_confirmada"
    HTTP_INVALIDO = "respuesta_http_no_valida"
    NO_HTML = "respuesta_no_html"
    HTML_VACIO = "respuesta_html_vacia"
    LIMITE_RESPUESTA = "limite_respuesta_excedido"
    LONGITUD_RESPUESTA = "longitud_respuesta_discordante"
    TRANSPORTE = "fallo_transporte_o_codificacion"


class EtapaSigac(str, Enum):
    NO_DETERMINADA = "no_determinada"
    PREPARACION = "preparacion"
    CREDENCIALES = "lectura_credenciales"
    CREACION_CLIENTE = "creacion_cliente"
    FORMULARIO = "formulario_acceso"
    LOGIN = "envio_login"
    REDIRECCION_LOGIN = "redireccion_login"
    SESION = "verificacion_sesion"
    SELECTOR_ROL = "selector_rol"
    ENVIO_ROL = "envio_rol"
    REDIRECCION_ROL = "redireccion_rol"
    PRINCIPAL = "pagina_principal"
    LISTADO_INICIAL = "listado_inicial"
    LISTADO_REPETIDO = "listado_repetido"
    HISTORIAL = "extraccion_historial"
    HISTORIAL_INICIAL = "historial_inicial"
    HISTORIAL_REPETIDO = "historial_repetido"
    BASELINE = "reconciliacion_baseline"
    RECONCILIACION = "reconciliacion_repetida"
    COMPARACION = "comparacion"
    CIERRE = "cierre_cliente"
    SALIDA = "salida"
    FINALIZADO = "finalizado"


class ContextoDiagnostico:
    """Único dato: etapa de catálogo cerrado. No guarda inputs, excepciones o DOM."""

    __slots__ = ("_etapa",)

    def __init__(self):
        self._etapa = EtapaSigac.PREPARACION

    @property
    def etapa(self):
        return self._etapa

    def marcar(self, etapa):
        self._etapa = etapa if isinstance(etapa, EtapaSigac) else EtapaSigac.NO_DETERMINADA


CLAVES_CONTEOS_BASE = (
    "tablas_documento", "filas_documento", "separadores_documento",
    "contenedores_coincidentes", "tablas_ambito", "filas_ambito",
    "separadores_ambito", "tablas_anexos_ambito", "enlaces_ambito",
    "tablas_envoltura", "tablas_internas_omitidas", "tablas_formulario_excluidas",
    "tablas_no_interpretadas", "tablas_con_bloques", "bloques_detectados",
    "bloques_vacios", "bloques_validos", "bloques_rechazados",
    "regiones_interactivas_excluidas", "filas_interactivas_excluidas",
)

# Solo existen cuando se rechaza una fila de anexo sin enlace utilizable
# (anexo_enlace_ausente). Describen esa fila rechazada: cantidades o 0/1,
# nunca textos, atributos, URLs ni posiciones.
CLAVES_ANEXO_AUSENTE = (
    "anexo_ausente_celdas_th",              # 0..2 celdas de la fila que son th
    "anexo_ausente_celda1_con_texto",       # 0/1
    "anexo_ausente_celda2_con_texto",       # 0/1
    "anexo_ausente_a_sin_href_celda2",      # <a> sin href en la segunda celda
    "anexo_ausente_a_href_celda1",          # <a href> en la primera celda
    "anexo_ausente_a_href_anidado_celda2",  # <a href> en tabla anidada de la segunda celda
    "anexo_ausente_imagenes_celda2",        # img
    "anexo_ausente_onclick_celda2",         # elementos con atributo onclick
    # Posición y contenido no visible de la segunda celda (ver parser._indicadores_posicion_*):
    "anexo_ausente_celda2_autocerrada",     # 0/1; ausente si no se pudo verificar en el original
    "anexo_ausente_a_fuera_de_celdas",      # <a href> hijo de la fila fuera de sus celdas
    "anexo_ausente_celda2_no_visibles",     # script, style y comentarios en la segunda celda
    "anexo_ausente_celda2_hijos",           # nodos hijos no vacíos de la segunda celda
    # Contexto de la tabla (indicios de forma, no prueba de atribución errónea):
    "anexo_ausente_tabla_en_fila_anexos",   # 0/1: cuelga de la fila «Anexos» de su propio bloque
    "anexo_ausente_filas_forma_cabecera",   # filas de la tabla con forma de cabecera de actuación
    "anexo_ausente_filas_equivalentes_otras_tablas",  # filas td/td vacías iguales en otras tablas
)

# Solo existen cuando una actuación se rechaza por controles y no se excluyó ninguna región.
# Enteros: conteos, 0/1 (`_ok`: 1 si el criterio se cumple) o categorías cerradas
# (`region_fila_previa_tipo`: 0 no hay, 1 separador, 2 vacía, 3 con tablaAnexos, 4 otra, 5 ancestro).
# Un valor que no puede determinarse se omite; nunca se sustituye por 0.
CLAVES_REGION_INTERACTIVA = (
    "region_ids_tabs", "region_es_div", "region_dentro_de_tabla",
    "region_celdas_fila", "region_elementos_ajenos_fila", "region_texto_ajeno_fila",
    "region_controles_dentro", "region_textareas", "region_envios", "region_paneles",
    "region_controles_fuera_en_prefijo", "region_controles_fuera_en_actuaciones", "region_controles_fuera_otros",
    "region_tablas_anexos_dentro", "region_filas_fecha_dentro",
    "region_filas_posteriores_no_vacias", "region_fila_previa_tipo",
    "region_bloques_con_controles_tras_quitar_fila",
    "region_c1_ok", "region_c2_ok", "region_c3_ok", "region_c4_ok", "region_c5_ok", "region_c6_ok", "region_c7_ok",
)

# Solo existen cuando una tabla se rechaza por `actuaciones_cabeceras_discordantes`.
CLAVES_CABECERAS = ("cabeceras_historicas_tabla", "actuaciones_extraidas_tabla")

CLAVES_CONTEOS = (CLAVES_CONTEOS_BASE + CLAVES_ANEXO_AUSENTE + CLAVES_REGION_INTERACTIVA
                 + CLAVES_CABECERAS + ("http_estado",))


def conteos_seguros(conteos):
    if not isinstance(conteos, dict):
        return {}
    resultado = {clave: conteos[clave] for clave in CLAVES_CONTEOS
                 if clave != "http_estado" and type(conteos.get(clave)) is int and conteos[clave] >= 0}
    # Estado HTTP, nunca encabezados ni datos procedentes del cuerpo.
    if type(conteos.get("http_estado")) is int and 100 <= conteos["http_estado"] <= 599:
        resultado["http_estado"] = conteos["http_estado"]
    return resultado


def diagnostico_seguro(codigo, conteos=None, *, etapa=EtapaSigac.NO_DETERMINADA):
    if not isinstance(codigo, CodigoHistorial):
        codigo = CodigoHistorial.NO_CLASIFICADO
    if not isinstance(etapa, EtapaSigac):
        etapa = EtapaSigac.NO_DETERMINADA
    return {"diagnostico_version": 2, "etapa": etapa.value, "categoria": codigo.value,
            "estadisticas_estructurales": conteos_seguros(conteos)}
