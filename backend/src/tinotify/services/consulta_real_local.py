"""Entrada persistente por posición cerrada hasta validar identidad institucional.

Conserva utilidades de etiqueta y derivación local; ninguna derivación acredita
estabilidad institucional ni autoriza elegir un expediente por posición.
Nada de este módulo se importa desde la API, que nunca inicia consultas reales.
"""

from uuid import UUID, uuid4, uuid5

from tinotify.demo.novedades import INSTANCIA_REAL

# Constante pública, no secreta: solo hace determinista el identificador local de cada expediente.
NAMESPACE_REAL = UUID("5b8e0d52-6c1f-4e0a-9a54-0f6d8f3f7a10")
ETIQUETA_PREDETERMINADA = "Expediente SIGAC"


class IdentidadExpedienteNoVerificada(ValueError):
    """No hay contrato institucional habilitado para continuidad persistente."""


def caso_local(numero):
    """Derivación local determinista; NO demuestra identidad institucional estable."""
    if type(numero) is not int or numero < 1:
        raise ValueError("Número de expediente no válido")
    return str(uuid5(NAMESPACE_REAL, f"{INSTANCIA_REAL}:{numero}"))


def exigir_identidad_expediente(politica, numero, instancia=INSTANCIA_REAL):
    """Compuerta común: sin contrato de expediente revisado Y habilitado, no hay consulta ni escritura reales.

    Solo prueba que la política vigente (catálogo de código revisado) nombra un contrato de
    «continuidad observada en la instancia»; no demuestra unicidad global ni ausencia de reutilización.
    """
    from tinotify.domain.identificadores import ContratoNoConfiable, PoliticaConfianza
    if not isinstance(politica, PoliticaConfianza):
        raise IdentidadExpedienteNoVerificada('Persistencia SIGAC bloqueada: falta una política de identidad explícita')
    try:
        return politica.exigir_expediente(numero, instancia)
    except ContratoNoConfiable:
        raise IdentidadExpedienteNoVerificada(
            'Persistencia SIGAC bloqueada: falta contrato verificado de identidad del expediente') from None


def etiqueta_valida(texto):
    texto = (texto or ETIQUETA_PREDETERMINADA).strip()
    if not texto or len(texto) > 60 or any(ord(c) < 32 or ord(c) == 127 for c in texto):
        raise ValueError("La etiqueta debe tener entre 1 y 60 caracteres sin controles.")
    return texto


def consultar_expediente(cliente, usuario, clave, *, tipo, total_casos, indice_caso, servicio, etiqueta=None,
                         caso_login=None, total_actuaciones=None, contenedor_id=None):
    """Entrada antigua cerrada; no autentica ni escribe usando índices del listado."""
    # Este flujo antiguo elegía por posición. Queda cerrado hasta disponer de
    # contrato de identidad de expediente, no de un UUID arbitrario del cliente.
    raise IdentidadExpedienteNoVerificada('Persistencia SIGAC bloqueada: identidad de expediente no verificada')


def consultar_caso_acreditado(cliente, usuario, clave, *, tipo, total_casos, caso_numero, servicio,
                              total_actuaciones=None, contenedor_id=None, caso_login=None):
    """UNA consulta manual real de un expediente acreditado por número; sin monitor ni notificaciones.

    La compuerta de identidad se evalúa ANTES de autenticar. Reutiliza `leer_historial_validado` (respuesta,
    identidad del detalle y parser) y `observar_validada` (reconciliador): la primera observación es línea base
    y no genera novedades. Devuelve solo cantidades y banderas.
    """
    from tinotify.integrations.sigac.lectura_validada import leer_historial_validado
    if getattr(getattr(servicio, "almacen", None), "perfil", None) != "real":
        raise IdentidadExpedienteNoVerificada("Persistencia SIGAC bloqueada: se requiere el almacén real v2")
    exigir_identidad_expediente(getattr(getattr(servicio, "observador", None), "politica", None), caso_numero)
    casos = cliente.autenticar(usuario, clave, tipo=tipo, total_casos_esperado=total_casos, caso_login=caso_login)
    if [c.numero for c in casos].count(caso_numero) != 1:
        raise IdentidadExpedienteNoVerificada("El caso no figura exactamente una vez en el listado validado")
    lectura = leer_historial_validado(cliente, caso_numero, total_esperado=total_actuaciones, contenedor_id=contenedor_id)
    resultado = servicio.observar_validada(lectura, clave=uuid4(),
                                           generacion_esperada=servicio.generacion(caso_local(caso_numero)))
    resultado.pop("caso", None)  # el identificador local no se emite
    return {**resultado, "lectura_real": True, "casos_listados": len(casos), "notificaciones": "no_activadas",
            "transferencia_externa": "no_autorizada"}
