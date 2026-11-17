"""Piezas de prueba del monitor real: SIGAC simulado con VARIOS expedientes y un almacén en memoria con el mismo contrato que AlmacenPg.

Todo ficticio. El almacén en memoria reutiliza `planificar` (la lógica de producción) y reproduce las escrituras de AlmacenPg para que las
mismas pruebas de contrato sirvan contra ambos.
"""

from collections import Counter
from copy import deepcopy
import itertools
import threading
from uuid import uuid4

import httpx

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_integridad_historial_sigac import COOKIE, FORMULARIO, SELECTOR, bloque, pagina
from tinotify.integrations.sigac.sigac_client import BASE_URL, SigacClient
from tinotify.real_remoto.almacen import AlmacenNoDisponible
from tinotify.real_remoto.monitor import EstadoPrevio, planificar


def listado(numeros):
    filas = "".join(f'<tr class="fila_enlace" onclick="abrir({n})"><td>{n}</td><td>CLIENTE_FICTICIO</td><td>FICTICIO</td></tr>'
                    for n in numeros)
    return f'<html><body><table><tr><th>Caso</th><th>Cliente</th><th>Estado</th></tr>{filas}</table></body></html>'


class SigacSimulado:
    """Servidor HTTP simulado. `casos`: {numero: [textos de actuaciones]} (mutable entre ejecuciones)."""

    def __init__(self, casos, *, usuario="USUARIO_FICTICIO_MONITOR", clave="CLAVE_FICTICIA_MONITOR", rechazar_login=False,
                 caidos=()):
        self.casos, self.usuario, self.clave = casos, usuario, clave
        self.rechazar_login, self.caidos = rechazar_login, set(caidos)
        self.llamadas, self.logins = [], 0

    def __call__(self, peticion):
        ruta = peticion.url.path.removeprefix("/sigac/")
        self.llamadas.append(ruta)
        cab = {"content-type": "text/html; charset=utf-8"}
        if ruta == "index.jsp":
            return httpx.Response(200, headers=cab, text=FORMULARIO)
        if ruta == "sesion.validar.ses":
            self.logins += 1
            if self.rechazar_login:
                return httpx.Response(200, headers=cab, text=FORMULARIO)
            return httpx.Response(302, headers={"location": "general.principal.con",
                                                "set-cookie": f"JSESSIONID={COOKIE}; Path=/sigac/; Secure; HttpOnly"})
        if ruta == "general.formCambiarTipoUsuario.con":
            return httpx.Response(200, headers=cab, text=SELECTOR)
        if ruta == "sesion.cambiar.ses":
            return httpx.Response(302, headers={"location": "general.principal.con"})
        if ruta == "general.principal.con":
            return httpx.Response(200, headers=cab, text="<html><body>PRINCIPAL_FICTICIA</body></html>")
        if ruta == "casos.seleccionarCasos.con":
            return httpx.Response(200, headers=cab, text=listado(sorted(self.casos)))
        if ruta == "casos.formCaso.con":
            numero = int(peticion.content.decode().split("hidCaso=")[1].split("&")[0])
            if numero in self.caidos or numero not in self.casos:
                return httpx.Response(500, headers=cab, text="<html><body>ERROR</body></html>")
            textos = self.casos[numero]
            cuerpo = pagina(*(bloque(t, fecha=f"2020-01-{1 + i % 28:02d} 10:00:00") for i, t in enumerate(textos))) if textos else "<html><body><form id=\"form1\"><table></table></form></body></html>"
            cuerpo = cuerpo.replace('<form id="form1">', "", 1).replace("</form>", "", 1)
            return httpx.Response(200, headers=cab, text=detalle(cuerpo, numero=str(numero)))
        raise AssertionError(f"Solicitud no prevista: {ruta}")

    def cliente(self):
        return SigacClient(httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self), follow_redirects=False))


class AlmacenMemoria:
    """Mismo contrato que AlmacenPg. `caido=True` simula una base inaccesible."""

    def __init__(self):
        self.cred = None
        self.estado_exp = {}   # ref -> {huellas, acreditado, generacion, anomalia}
        self.avisos = {}       # id -> dict
        self.ejecuciones = []  # dicts
        self.caido = False
        self._bloqueo = threading.Lock()
        self.escrituras_de_huellas = 0

    def _vivo(self):
        if self.caido:
            raise AlmacenNoDisponible

    def verificar(self):
        self._vivo()

    def credenciales(self):
        self._vivo()
        return deepcopy(self.cred)

    def guardar_credenciales(self, version, nonce, cifrado):
        self._vivo()
        self.cred = (version, bytes(nonce), bytes(cifrado))

    def olvidar_credenciales(self):
        self._vivo()
        habia, self.cred = self.cred is not None, None
        return habia

    def iniciar_ejecucion(self):
        self._vivo()
        ejecucion = {"id": str(uuid4()), "resultado": "en_curso", "expedientes": None, "novedades": None, "codigo": None}
        self.ejecuciones.append(ejecucion)
        return ejecucion["id"]

    def cerrar_ejecucion(self, ejecucion, resultado, expedientes=None, novedades=None, codigo=None):
        self._vivo()
        fila = next(e for e in self.ejecuciones if e["id"] == ejecucion)
        fila.update(resultado=resultado, expedientes=expedientes, novedades=novedades, codigo=codigo)

    def aplicar(self, lecturas, semillas):
        self._vivo()
        with self._bloqueo:
            previos = {r: EstadoPrevio(Counter(e["huellas"]), e["acreditado"], e["generacion"], e["anomalia"])
                       for r, e in self.estado_exp.items()}
            plan = planificar(previos, lecturas, semillas)
            for c in plan.cambios:
                if c.accion == "anomalia" and c.en_bd:
                    self.estado_exp[c.caso_ref]["anomalia"] = True
                    continue
                if c.accion in ("nuevo", "novedades") or not c.en_bd:
                    self.escrituras_de_huellas += 1
                    self.estado_exp[c.caso_ref] = {"huellas": Counter(c.huellas), "acreditado": c.acreditado,
                                                   "generacion": c.generacion, "anomalia": c.anomalia}
                else:
                    self.estado_exp[c.caso_ref].update(anomalia=c.anomalia, generacion=c.generacion)
            aviso = None
            if plan.requiere_aviso:
                aviso = str(uuid4())
                self.avisos[aviso] = {"id": aviso, "expedientes_con_novedades": plan.expedientes_con_novedades,
                                      "novedades": plan.novedades, "expedientes_nuevos": plan.expedientes_nuevos,
                                      "anomalias": plan.anomalias, "intentos": 0, "entregado": False, "orden": next(_ORDEN)}
            return plan, aviso

    def avisos_pendientes(self):
        self._vivo()
        return [{k: v for k, v in a.items() if k not in ("entregado", "orden")}
                for a in sorted(self.avisos.values(), key=lambda a: a["orden"]) if not a["entregado"]]

    def marcar_entregado(self, aviso):
        self._vivo()
        a = self.avisos.get(aviso)
        if a is None or a["entregado"]:
            return False
        a.update(entregado=True, intentos=a["intentos"] + 1)
        return True

    def estado(self):
        self._vivo()
        ultima = self.ejecuciones[-1] if self.ejecuciones else None
        return {"credenciales_guardadas": self.cred is not None, "expedientes_en_estado": len(self.estado_exp),
                "avisos_pendientes": len(self.avisos_pendientes()),
                "ultima_ejecucion": None if ultima is None else {"resultado": ultima["resultado"], "inicio": "t", "fin": "t"}}


_ORDEN = itertools.count()
