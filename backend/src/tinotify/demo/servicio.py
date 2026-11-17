"""Una instancia demo en memoria: caduca al reiniciar, sin persistencia oculta."""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
from threading import RLock
import time
from uuid import uuid4

from tinotify.demo.sigac_simulado import SigacSimulado
from tinotify.domain.notificaciones import crear_notificacion
from tinotify.services.reconciliacion import reconciliar


class AccesoDemo(Exception):
    pass


class ConflictoDemo(Exception):
    pass


def huella(valor):
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


@dataclass(repr=False)
class Cuenta:
    nombre: str
    caso: str = field(default_factory=lambda: str(uuid4()))
    estado: dict | None = None
    vista: list = field(default_factory=list)
    eventos: list = field(default_factory=list)
    solicitudes: set = field(default_factory=set)
    dispositivo: dict | None = None


class ServicioDemo:
    def __init__(self, codigos, origen=None, reloj=time.monotonic):
        if len(codigos) != 2 or any(not isinstance(c, str) or len(c) < 24 for c in codigos) or codigos[0] == codigos[1]:
            raise ValueError("Se requieren dos codigos demo distintos de al menos 24 caracteres")
        self._codigos = [huella(c) for c in codigos]
        self._cuentas = [Cuenta("Estudiante demo A"), Cuenta("Estudiante demo B")]
        self._sesiones = {}
        self._origen = origen or SigacSimulado()
        self._reloj = reloj
        self._lock = RLock()
        for cuenta in self._cuentas:
            self._origen.crear(cuenta.caso)

    def ingresar(self, codigo):
        with self._lock:
            indice = next((i for i,c in enumerate(self._codigos) if hmac.compare_digest(c, huella(codigo))), None)
            if indice is None:
                raise AccesoDemo
            self._retirar(indice)
            token = secrets.token_urlsafe(32)
            self._sesiones[huella(token)] = (indice, self._reloj()+3600)
            return token

    def _indice(self, token):
        dato = self._sesiones.get(huella(token))
        if dato is None or dato[1] <= self._reloj():
            raise AccesoDemo
        return dato[0]

    def _retirar(self, indice):
        self._sesiones = {t:d for t,d in self._sesiones.items() if d[0] != indice}
        cuenta = self._cuentas[indice]
        cuenta.dispositivo = None
        for e in cuenta.eventos:
            if e["estado"] in ("pendiente", "enviando", "reintentable"):
                e["estado"] = "sesion_cerrada"

    def salir(self, token):
        with self._lock:
            self._retirar(self._indice(token))

    def cuenta(self, token, caso=None):
        cuenta = self._cuentas[self._indice(token)]
        if caso is not None and cuenta.caso != caso:
            raise KeyError
        return cuenta

    def listar(self, token):
        with self._lock:
            c = self.cuenta(token)
            return [{"id": c.caso, "titulo": "Proceso ficticio de demostracion", "estudiante": c.nombre}]

    def _sincronizar(self, c):
        observaciones = self._origen.observar(c.caso)
        if not observaciones:
            raise ConnectionError
        siguiente, resultado = reconciliar(c.estado, list(observaciones), caso=c.caso, instancia="demo")
        vista = [{"fecha": a.fecha.isoformat(), "descripcion": a.descripcion, "direccion": a.direccion}
                 for a in observaciones]
        nuevos = []
        for cambio in resultado.eventos:
            aviso = crear_notificacion(0, cambio.direccion, cambio.tipo)
            nuevos.append({"id": str(uuid4()), "caso": c.caso, "mensaje": aviso.mensaje,
                           "tipo": cambio.tipo.value, "prioridad": aviso.prioridad.value,
                           "estado": "pendiente", "ticket": None, "binding": None})
        c.estado, c.vista, c.eventos = siguiente, vista, c.eventos+nuevos

    def sincronizar(self, token, caso):
        with self._lock:
            self._sincronizar(self.cuenta(token, caso))
            return self.detalle(token, caso)

    def agregar(self, token, caso, solicitud):
        with self._lock:
            c = self.cuenta(token, caso)
            if c.estado is None:
                self._sincronizar(c)  # Nunca enviar el historial de primera observacion.
            if solicitud not in c.solicitudes:
                if len(c.solicitudes) >= 50:
                    raise ConflictoDemo
                self._origen.agregar(caso)
                c.solicitudes.add(solicitud)
            self._sincronizar(c)
            return self.detalle(token, caso)

    def detalle(self, token, caso):
        with self._lock:
            c = self.cuenta(token, caso)
            return {"id": c.caso, "titulo": "Proceso ficticio de demostracion", "historial": deepcopy(c.vista),
                    "avisos": [{k:v for k,v in e.items() if k not in ("binding","ticket")} for e in c.eventos],
                    "demo": True, "persistencia": "memoria"}

    def registrar(self, token, push_token):
        with self._lock:
            c = self.cuenta(token)
            if any(otra is not c and otra.dispositivo and otra.dispositivo["token"] == push_token for otra in self._cuentas):
                raise ConflictoDemo
            if not c.dispositivo or c.dispositivo["token"] != push_token:
                c.dispositivo = {"token": push_token, "binding": str(uuid4())}

    def tomar_envios(self, token):
        with self._lock:
            c = self.cuenta(token)
            if not c.dispositivo:
                return []
            envios = []
            for e in c.eventos:
                if e["estado"] not in ("pendiente","reintentable"):
                    continue
                if e["binding"] not in (None,c.dispositivo["binding"]):
                    e["estado"] = "sesion_cerrada"
                    continue
                e["binding"] = c.dispositivo["binding"]
                e["estado"] = "enviando"
                envios.append((c.dispositivo["token"], deepcopy(e)))
            return envios

    def resolver_envio(self, token, evento, estado, ticket):
        with self._lock:
            c = self.cuenta(token)
            e = next(e for e in c.eventos if e["id"] == evento["id"])
            if e["estado"] == "enviando" and c.dispositivo and e["binding"] == c.dispositivo["binding"]:
                e["estado"], e["ticket"] = estado, ticket
                if estado == "dispositivo_invalido":
                    c.dispositivo = None

    def tickets(self, token):
        with self._lock:
            return [e["ticket"] for e in self.cuenta(token).eventos if e["estado"] == "aceptado_expo" and e["ticket"]]

    def aplicar_recibos(self, token, recibos):
        with self._lock:
            c = self.cuenta(token)
            for e in c.eventos:
                recibo = recibos.get(e["ticket"], {})
                if e["estado"] != "aceptado_expo" or not isinstance(recibo, dict):
                    continue
                if recibo.get("status") == "ok":
                    e["estado"] = "aceptado_fcm"
                elif recibo.get("status") == "error":
                    e["estado"] = "rechazado"
