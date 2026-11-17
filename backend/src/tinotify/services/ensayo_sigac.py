"""Ensayo acotado de lectura; estado y HTML transitorios, sin monitor en disco."""

from collections import Counter

from tinotify.integrations.sigac.sigac_client import SigacClientError
from tinotify.services.reconciliacion import reconciliar
from tinotify.parsers.diagnostico_historial import CodigoHistorial, ContextoDiagnostico, EtapaSigac


def _anexos_sin_enlace(actuaciones) -> int:
    """Solo una cantidad: anexos con descripción extraídos sin referencia de descarga."""
    return sum(1 for actuacion in actuaciones for anexo in actuacion.anexos if anexo.sin_enlace)


def _conteo_interactivo(cliente, clave):
    """Entero de la última consulta o None si el cliente no lo informa (nunca se inventa un 0)."""
    datos = getattr(cliente, "ultimo_conteo_interactivo", None)
    valor = datos.get(clave) if isinstance(datos, dict) else None
    return valor if type(valor) is int and valor >= 0 else None


def ejecutar_ensayo(cliente, usuario, clave, *, tipo, total_casos, total_actuaciones=None,
                    indice_caso=1, repeticiones=2, contenedor_id=None, caso_login=None, diagnostico=False):
    contexto = getattr(cliente, "contexto", None)
    if not isinstance(contexto, ContextoDiagnostico):
        contexto = ContextoDiagnostico()
    contexto.marcar(EtapaSigac.PREPARACION)
    if type(repeticiones) is not int or not 2 <= repeticiones <= 3:
        raise SigacClientError("El ensayo requiere dos o tres consultas en total.",
                               codigo=CodigoHistorial.ENTRADA_INVALIDA, etapa=contexto.etapa)
    if type(indice_caso) is not int or not 1 <= indice_caso <= total_casos:
        raise SigacClientError("Selecciona una posición válida del listado contrastado.",
                               codigo=CodigoHistorial.ENTRADA_INVALIDA, etapa=contexto.etapa)
    contexto.marcar(EtapaSigac.FORMULARIO)
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos,
                              caso_login=caso_login)
    caso = casos[indice_caso - 1]
    ids_iniciales = {c.numero for c in casos}
    contexto.marcar(EtapaSigac.HISTORIAL_INICIAL)
    iniciales = cliente.consultar_historial(caso.numero, total_esperado=total_actuaciones,
                                            contenedor_id=contenedor_id, diagnostico=diagnostico)
    contexto.marcar(EtapaSigac.BASELINE)
    estado, linea_base = reconciliar(None, list(iniciales), caso=str(caso.numero), instancia="sigac-ensayo")
    if linea_base.eventos:
        raise SigacClientError("La línea base produjo eventos inesperados.",
                               codigo=CodigoHistorial.BASELINE_INVALIDO, etapa=contexto.etapa)
    contexto.marcar(EtapaSigac.COMPARACION)
    referencia = Counter(a.huella_version for a in iniciales)
    estable, eventos = True, 0
    cantidades, comparaciones = [len(iniciales)], []
    sin_enlace = [_anexos_sin_enlace(iniciales)]
    regiones = [_conteo_interactivo(cliente, "regiones_interactivas_excluidas")]
    filas_excluidas = [_conteo_interactivo(cliente, "filas_interactivas_excluidas")]
    for consulta in range(2, repeticiones + 1):
        contexto.marcar(EtapaSigac.LISTADO_REPETIDO)
        nuevos_casos = cliente.listar_casos(total_esperado=total_casos)
        if {c.numero for c in nuevos_casos} != ids_iniciales:
            raise SigacClientError("El listado cambió durante el ensayo; requiere revisión.",
                                   codigo=CodigoHistorial.LISTADO_CAMBIADO, etapa=contexto.etapa)
        contexto.marcar(EtapaSigac.HISTORIAL_REPETIDO)
        siguientes = cliente.consultar_historial(caso.numero, total_esperado=total_actuaciones,
                                                 contenedor_id=contenedor_id, diagnostico=diagnostico)
        contexto.marcar(EtapaSigac.RECONCILIACION)
        siguiente_estado, resultado = reconciliar(estado, list(siguientes), caso=str(caso.numero), instancia="sigac-ensayo")
        contexto.marcar(EtapaSigac.COMPARACION)
        observadas = Counter(a.huella_version for a in siguientes)
        iguales = observadas == referencia
        cantidades.append(len(siguientes))
        sin_enlace.append(_anexos_sin_enlace(siguientes))
        regiones.append(_conteo_interactivo(cliente, "regiones_interactivas_excluidas"))
        filas_excluidas.append(_conteo_interactivo(cliente, "filas_interactivas_excluidas"))
        comparaciones.append({"consulta": consulta, "sin_cambios": iguales,
                              "ocurrencias_no_presentes_en_base": (observadas - referencia).total(),
                              "ocurrencias_no_observadas": (referencia - observadas).total()})
        estable = estable and iguales
        eventos += len(resultado.eventos)
        estado = siguiente_estado
    return {"resultado": "estable" if estable else "cambios_observados",
            "lectura_funcional": True,
            "completitud": "completitud_no_verificada" if total_actuaciones is None else "total_contrastado",
            "casos": len(casos), "actuaciones": len(iniciales), "consultas_historial": repeticiones,
            "actuaciones_por_consulta": cantidades, "anexos_sin_enlace_por_consulta": sin_enlace,
            "regiones_interactivas_excluidas_por_consulta": regiones,
            "filas_interactivas_excluidas_por_consulta": filas_excluidas,
            "comparaciones": comparaciones,
            "eventos_baseline": len(linea_base.eventos), "eventos_posteriores": eventos,
            "persistencia": "ninguna"}
