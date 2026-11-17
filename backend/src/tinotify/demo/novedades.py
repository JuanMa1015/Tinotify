"""Detección y consulta local: entradas sintéticas y entrada SIGAC acreditada separadas.

Orquesta servicios existentes (`ServicioSeguimiento`, `ServicioAvisos`) sobre el almacén SQLite de
desarrollo. No contiene lógica de reconciliación propia ni ejecuta HTTP.
Consultar una novedad nunca la marca como procesada; ese paso no se expone por la API.
"""

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json
from uuid import uuid4

from tinotify.domain.actuaciones import Actuacion
from tinotify.parsers.parser import PREFIJO_FILAS, ErrorParseoHistorial, parse_actuaciones
from tinotify.persistence.sqlite_local import (
    BINDING_LOCAL, CREDENCIAL_LOCAL, AlmacenSqliteLocal,
)
from tinotify.services.avisos_persistentes import ServicioAvisos
from tinotify.services.seguimiento import ServicioSeguimiento
from tinotify.services.observacion_local import ObservacionRechazada, ObservadorLocal, contenido_logico
from tinotify.domain.actuaciones import resumir


CASO_OBSERVADO = "00000000-0000-4000-8000-0000000000c1"
TITULO_OBSERVADO = "Proceso sintético observado"
INSTANCIA = "demo-local"
INSTANCIA_REAL = "sigac-real"


def _semantica_real():
    # Semántica de consulta constante, no una autorización aportada por el cliente.
    return {'contrato_version': 1, 'cobertura': 'desconocida',
            'referencia': 'ocurrencias_observadas', 'entrega_externa': 'no_autorizada'}


def html_historial_sintetico(cantidad):
    """Historial HTML ficticio con `cantidad` actuaciones, en el formato que el parser ya reconoce."""
    if type(cantidad) is not int or not 1 <= cantidad <= 200:
        raise ValueError("Cantidad de actuaciones sintéticas no válida")
    base = datetime(2026, 2, 1, 9, 0, 0)
    bloques = []
    for n in range(cantidad):
        direccion = "ASESOR--&gt;ESTUDIANTE" if n % 2 else "ESTUDIANTE--&gt;ASESOR"
        bloques.append(
            '<tr><td colspan="2"><hr></td></tr>'
            f'<tr><td>TITULO SINTETICO {n + 1}</td><td>{direccion}</td></tr>'
            f'<tr><td>{(base + timedelta(hours=n)).strftime("%Y-%m-%d %H:%M:%S")}</td><td>REMITENTE SINTETICO</td></tr>'
            f'<tr><td>Actuación :</td><td>Actuación sintética número {n + 1}.</td></tr>')
    return '<html><body><form id="form1"><table>' + "".join(bloques) + "</table></form></body></html>"


def _texto_legible(descripcion):
    """El parser codifica varias filas como JSON con prefijo; se muestran como «Etiqueta: texto»."""
    if descripcion.startswith(PREFIJO_FILAS):
        try:
            filas = json.loads(descripcion[len(PREFIJO_FILAS):])["filas"]
            return "\n".join(f"{e}: {t}" if e else t for e, t in filas)
        except (ValueError, KeyError, TypeError):
            return descripcion
    return descripcion


def _contenido(a):
    return {"fecha": a.fecha.isoformat(), "titulo": a.etapa, "direccion": a.direccion, "remitente": a.remitente,
            "descripcion": _texto_legible(a.descripcion),
            "anexos": [{"descripcion": x.descripcion, "sin_enlace": x.sin_enlace} for x in a.anexos]}


class ServicioNovedadesLocal:
    def __init__(self, almacen: AlmacenSqliteLocal, *, instancia=INSTANCIA):
        self.almacen = almacen
        self.sintetico = almacen.perfil == "sintetico"
        self.seguimiento = ServicioSeguimiento(almacen, instancia=instancia)
        self.avisos = ServicioAvisos(almacen)
        self.observador = ObservadorLocal(almacen, instancia)

    # --- Escritura: solo desde herramientas locales; la API no la expone ----------------------------
    def observar_html(self, caso, html, *, titulo=TITULO_OBSERVADO, clave=None, generacion_esperada=None):
        """Solo fixtures sintéticas de un llamador local de confianza; no es una entrada SIGAC."""
        if self.almacen.perfil == 'real' or self.observador.instancia == INSTANCIA_REAL:
            raise PermissionError('HTML directo no autorizado para origen real')
        documento = BeautifulSoup(html, 'html.parser')
        # Solo es una guarda de rechazo, nunca una acreditación de identidad.
        if (documento.find(attrs={'name': 'hidCaso'}) or documento.find(id='hidCaso')
                or documento.find('form', attrs={'action': 'casos.guardarCaso.con'})
                or documento.find(string=lambda t: 'Información del caso Nro.' in t)):
            raise PermissionError('El detalle SIGAC no es entrada sintetica')
        if clave is None and generacion_esperada is None:
            # Conveniencia de simulación: capturar la precondición ANTES del
            # parseo. La operación atómica siempre recibe ambos datos.
            clave, generacion_esperada = uuid4(), self.generacion(caso)
        elif clave is None or generacion_esperada is None:
            raise ValueError('Clave y generacion deben proporcionarse juntas')
        try:
            actuaciones = parse_actuaciones(html, caso)
        except ErrorParseoHistorial as error:
            raise ObservacionRechazada(f"Extracción rechazada ({error.codigo.value}); estado sin cambios.") from None
        return self.observar(caso, actuaciones, titulo=titulo, clave=clave, generacion_esperada=generacion_esperada)

    def generacion(self, caso):
        return self.observador.generacion(caso)

    def consultar_recibo(self, caso, actuaciones, *, clave, generacion_esperada, titulo=TITULO_OBSERVADO):
        digest = resumir(contenido_logico(self.observador.instancia, caso, self.almacen.perfil,
            self.observador.politica, actuaciones, titulo, generacion_esperada))
        return self.observador.consultar_recibo(caso, clave, digest)

    def observar(self, caso, actuaciones, *, clave, generacion_esperada, titulo=TITULO_OBSERVADO):
        from tinotify.integrations.sigac.lectura_validada import HistorialSigac, LecturaSigacValidada
        if isinstance(actuaciones, (HistorialSigac, LecturaSigacValidada)):
            raise PermissionError('Usar la entrada de lectura validada para datos SIGAC')
        actuaciones = list(actuaciones)
        recibo, novedades = self.observador.observar(caso, actuaciones, clave=clave,
            generacion_esperada=generacion_esperada, titulo=titulo, contenido_vista=_contenido)
        return {"baseline": recibo.generacion == 1, "novedades_nuevas": novedades, "actuaciones": len(actuaciones),
                "generacion": recibo.generacion}

    def observar_validada(self, lectura, *, clave, generacion_esperada):
        caso, recibo, novedades, cantidad = self.observador.observar_validada(
            lectura, clave=clave, generacion_esperada=generacion_esperada)
        return {'caso': caso, 'baseline': recibo.generacion == 1, 'novedades_nuevas': novedades,
                'actuaciones': cantidad, 'generacion': recibo.generacion}

    # --- Lectura (la API solo usa estos métodos) -----------------------------------------------------
    def listar_casos(self):
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            if self.almacen.perfil == 'real':
                eventos = unidad.observaciones_internas()
                return [{**_semantica_real(), 'id': c['caso'], 'titulo': c['titulo'],
                         'generacion': c['generacion'], 'referencia_establecida': True,
                         'ocurrencias_observadas': len(unidad.vista(c['caso'])['actuaciones']),
                         'eventos_internos': sum(e['caso'] == c['caso'] for e in eventos)}
                        for c in unidad.casos()]
            pendientes = unidad.pendientes_por_caso()
            return [{"id": c["caso"], "titulo": c["titulo"], "generacion": c["generacion"],
                     "total_actuaciones": len(unidad.vista(c["caso"])["actuaciones"]),
                     "novedades_pendientes": pendientes.get(c["caso"], 0), "demo": self.sintetico}
                    for c in unidad.casos()]

    def detalle(self, caso):
        """KeyError si el caso no existe o no tiene baseline."""
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            vista = unidad.vista(caso)
            if self.almacen.perfil == 'real':
                return {**_semantica_real(), 'id': caso, 'titulo': vista['titulo'],
                        'generacion': vista['generacion'], 'referencia_establecida': True,
                        'ocurrencias_observadas': len(vista['actuaciones']),
                        'eventos_internos': sum(e['caso'] == caso for e in unidad.observaciones_internas()),
                        'ocurrencias': [{'local_id': a['local_id'], 'generacion': a['generacion']}
                                        for a in vista['actuaciones']]}
            avisos = self.avisos.pendientes(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
            afectadas = {v["local_id"] for v in unidad.eventos_pendientes_con_caso([a.id for a in avisos]).values()
                         if v["caso"] == caso}
            pendientes = unidad.pendientes_por_caso().get(caso, 0)
        return {"id": caso, "titulo": vista["titulo"], "generacion": vista["generacion"], "baseline": True,
                "total_actuaciones": len(vista["actuaciones"]), "novedades_pendientes": pendientes,
                "demo": self.sintetico, "sintetico": self.sintetico,
                "actuaciones": [{**{k: v for k, v in a.items() if k != "huella"}, "nueva": a["local_id"] in afectadas}
                                for a in vista["actuaciones"]]}

    def novedades(self):
        if self.almacen.perfil == 'real':
            raise PermissionError('Avisos reales deshabilitados; consultar observaciones internas')
        avisos = self.avisos.pendientes(CREDENCIAL_LOCAL, binding=BINDING_LOCAL)
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            relacion = unidad.eventos_pendientes_con_caso([a.id for a in avisos])
            vistas = {}
            resultado = []
            for aviso in avisos:
                dato = relacion.get(str(aviso.id))
                if dato is None:
                    continue
                vistas.setdefault(dato["caso"], unidad.vista(dato["caso"]))
                actuacion = next((a for a in vistas[dato["caso"]]["actuaciones"] if a["local_id"] == dato["local_id"]), None)
                resultado.append({
                    "id": str(aviso.id), "caso": dato["caso"], "tipo": aviso.notificacion.tipo.value,
                    "prioridad": aviso.notificacion.prioridad.value, "titulo": aviso.notificacion.titulo,
                    "mensaje": aviso.notificacion.mensaje,
                    "actuacion": None if actuacion is None else {k: v for k, v in actuacion.items() if k != "huella"},
                })
        return resultado

    def observaciones(self):
        """Consulta real mínima. Primera observación no acredita creación reciente."""
        if self.almacen.perfil != 'real':
            raise PermissionError('La demo conserva su contrato de novedades sinteticas')
        with self.almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
            eventos = unidad.observaciones_internas()
        return {**_semantica_real(), 'observaciones': [
            {**evento, 'creacion_reciente_acreditada': False} for evento in eventos]}
