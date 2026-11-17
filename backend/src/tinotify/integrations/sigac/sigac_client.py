"""Contrato HTTP SIGAC observado; un cliente por cuenta, cookies solo en RAM."""

from http.cookies import SimpleCookie, CookieError
from urllib.parse import unquote, urlsplit

import httpx

from tinotify.integrations.sigac.sigac_roles import RolSigac, datos_seleccion_rol
from tinotify.integrations.sigac.observacion_login import observar_destino_login
from tinotify.integrations.sigac.sigac_identidad import ErrorIdentidadRespuesta, validar_detalle
from tinotify.integrations.sigac.lectura_validada import HistorialSigac
from tinotify.integrations.sigac.sigac_respuestas import (
    RespuestaIncompleta, destino_confirmado, destino_login_confirmado, es_acceso, es_selector, leer_acceso,
    pagina_protegida, verificar_selector_estudiante,
)
from tinotify.parsers.casos_parser import extraer_casos
from tinotify.parsers.parser import ErrorParseoHistorial, estadisticas_documento, parse_actuaciones
from tinotify.parsers.diagnostico_historial import (
    CodigoHistorial, ContextoDiagnostico, EtapaSigac, diagnostico_seguro,
)


BASE_URL = "https://sigac.udea.edu.co/sigac/"
LISTADO = "casos.seleccionarCasos.con?motivo=ACTUAR_ESTUDIANTE"
MAX_HTML_BYTES = 8 * 1024 * 1024


class SigacClientError(Exception):
    """Error genérico sin cuerpos HTTP, credenciales ni cookies."""

    def __init__(self, mensaje, *, codigo=CodigoHistorial.NO_CLASIFICADO, diagnostico=None,
                 etapa=EtapaSigac.NO_DETERMINADA):
        super().__init__(mensaje)
        self.codigo = codigo if isinstance(codigo, CodigoHistorial) else CodigoHistorial.NO_CLASIFICADO
        self.diagnostico = diagnostico
        self.etapa = etapa if isinstance(etapa, EtapaSigac) else EtapaSigac.NO_DETERMINADA


class SigacSessionExpired(SigacClientError):
    """La sesión ya no permite acceder al recurso."""


class SigacIdentityError(SigacClientError):
    """No se confirmó consistencia del detalle; nunca entregar actuaciones parciales."""


class SigacClient:
    """Sin persistencia ni reintentos automáticos de autenticación.

    La instancia no se comparte entre cuentas ni se usa concurrentemente.
    El cliente inyectado es una frontera de confianza destinada a pruebas.
    """

    def __init__(self, http_client: httpx.Client | None = None):
        self.contexto = ContextoDiagnostico()
        if http_client is not None and http_client.base_url != httpx.URL(BASE_URL):
            raise ValueError("El cliente debe utilizar el origen SIGAC confirmado.")
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(
            base_url=BASE_URL, timeout=10.0, follow_redirects=False,
            verify=True, trust_env=False,
        )
        self._confirmada = False
        self._casos = set()
        self.ultimo_conteo_interactivo = None

    def _anotar_error(self, error):
        if error.etapa is EtapaSigac.NO_DETERMINADA:
            error.etapa = self.contexto.etapa

    @property
    def autenticada(self):
        # Nombre histórico: acceso al listado, no prueba independiente del rol.
        return self._confirmada and self._tiene_cookie(LISTADO)

    @property
    def rol_activo_confirmado(self):
        """No hay señal positiva comprobada de rol activo; nunca inferirla del 302."""
        return False

    def _invalidar(self):
        self._confirmada = False
        self._casos.clear()
        self.http.cookies.clear()

    @staticmethod
    def _validar_ruta(ruta: str) -> str:
        if not isinstance(ruta, str) or not ruta or any(ord(c) <= 32 for c in ruta):
            raise ValueError("Ruta no permitida.")
        parsed = urlsplit(ruta)
        path = unquote(parsed.path)
        if (parsed.scheme or parsed.netloc or parsed.fragment or chr(92) in ruta or chr(92) in path
                or not path or path.startswith("/")
                or any(s in (".", "..") for s in path.split("/"))
                or any(ord(c) < 32 for c in path)):
            raise ValueError("La ruta debe ser relativa a SIGAC y no contener escapes de ruta.")
        return ruta

    def _solicitar(self, metodo, ruta, *, datos=None):
        """Lee con límite; nunca propaga excepciones HTTP con request sensible."""
        ruta = self._validar_ruta(ruta)
        resultado = None
        try:
            with self.http.stream(metodo, ruta, data=datos, follow_redirects=False) as respuesta:
                partes, longitud = [], 0
                for parte in respuesta.iter_bytes():
                    longitud += len(parte)
                    if longitud > MAX_HTML_BYTES:
                        raise SigacClientError("Respuesta demasiado grande; no se procesó.",
                                               codigo=CodigoHistorial.LIMITE_RESPUESTA)
                    partes.append(parte)
                contenido = b"".join(partes)
                if not respuesta.headers.get("content-encoding") and "content-length" in respuesta.headers:
                    try:
                        declarada = int(respuesta.headers["content-length"])
                    except ValueError:
                        declarada = -1
                    if declarada != len(contenido):
                        raise SigacClientError("Respuesta incompleta; no se procesó.",
                                               codigo=CodigoHistorial.LONGITUD_RESPUESTA)
                resultado = (respuesta.status_code, respuesta.headers,
                             contenido.decode(respuesta.encoding or "utf-8", errors="strict"))
        except (httpx.HTTPError, UnicodeError, LookupError):
            pass
        if resultado is None:
            raise SigacClientError("Error de comunicación o codificación; no se procesó la respuesta.",
                                   codigo=CodigoHistorial.TRANSPORTE)
        return resultado

    def _html(self, respuesta, *, permitir_acceso=False, permitir_selector=False):
        estado, cabeceras, html = respuesta
        if estado in (401, 403) or 300 <= estado < 400:
            self._invalidar()
            raise SigacSessionExpired("Sesión no confirmada o vencida.", codigo=CodigoHistorial.SESION_NO_CONFIRMADA)
        if estado != 200:
            raise SigacClientError("Respuesta HTTP no válida; no se procesó.", codigo=CodigoHistorial.HTTP_INVALIDO)
        if cabeceras.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
            raise SigacClientError("SIGAC no devolvió contenido HTML.", codigo=CodigoHistorial.NO_HTML)
        if not html.strip():
            raise SigacClientError("Respuesta HTML vacía; no se procesó.", codigo=CodigoHistorial.HTML_VACIO)
        if not permitir_acceso and es_acceso(html):
            self._invalidar()
            raise SigacSessionExpired("SIGAC devolvió el formulario de acceso.", codigo=CodigoHistorial.SESION_NO_CONFIRMADA)
        if not permitir_selector and es_selector(html):
            self._invalidar()
            raise SigacSessionExpired("SIGAC volvió a la selección de rol.", codigo=CodigoHistorial.SESION_NO_CONFIRMADA)
        return html

    def obtener_html(self, ruta: str) -> str:
        """Compatibilidad de bajo nivel; no demuestra autenticación por sí sola."""
        return self._html(self._solicitar("GET", ruta))

    def _tiene_cookie(self, ruta):
        # build_request aplica dominio, path, Secure y caducidad del cookie jar.
        cabecera = self.http.build_request("GET", ruta).headers.get("cookie", "")
        cookies = SimpleCookie()
        try:
            cookies.load(cabecera)
        except CookieError:
            return False
        nombres = [parte.strip().split("=", 1)[0] for parte in cabecera.split(";")]
        return nombres.count("JSESSIONID") == 1 and bool(cookies.get("JSESSIONID") and cookies["JSESSIONID"].value)

    def seleccionar_rol(self, rol: RolSigac) -> str:
        """Operación existente: el 302 solo indica un destino por verificar."""
        datos = datos_seleccion_rol(rol)
        self._confirmada = False
        self._casos.clear()
        self.contexto.marcar(EtapaSigac.ENVIO_ROL)
        estado, cabeceras, _ = self._solicitar("POST", "sesion.cambiar.ses", datos=datos)
        if estado in (401, 403):
            self._invalidar()
            raise SigacSessionExpired("Sesión no autorizada o vencida.",
                                      codigo=CodigoHistorial.SESION_NO_CONFIRMADA, etapa=self.contexto.etapa)
        if estado != 302:
            raise SigacClientError("Respuesta inesperada al seleccionar rol.",
                                   codigo=CodigoHistorial.ROL_RESPUESTA_INVALIDA, etapa=self.contexto.etapa)
        self.contexto.marcar(EtapaSigac.REDIRECCION_ROL)
        try:
            return destino_confirmado(cabeceras.get("location", ""), {"general.principal.con"})
        except RespuestaIncompleta as error:
            self._invalidar()
            raise SigacClientError("Redirección de rol no confirmada.", codigo=error.codigo,
                                   etapa=self.contexto.etapa) from None

    def _enviar_login(self, usuario, clave, *, tipo, caso_login):
        """GET y POST originales compartidos; no sigue ninguna redirección."""
        self.contexto.marcar(EtapaSigac.FORMULARIO)
        formulario = leer_acceso(self._html(self._solicitar("GET", "index.jsp"), permitir_acceso=True))
        if tipo not in formulario.tipos:
            raise RespuestaIncompleta("El tipo solicitado no es una opción del formulario.",
                                     codigo=CodigoHistorial.TIPO_NO_OFRECIDO)
        datos = {"cboTipo": tipo, "txtUsuario": usuario,
                 "txtCaso": formulario.caso if caso_login is None else caso_login,
                 "txtClave": clave, "cmdIngresar": formulario.ingresar}
        self.contexto.marcar(EtapaSigac.LOGIN)
        return self._solicitar("POST", "sesion.validar.ses", datos=datos)

    def _verificar_estado_login(self, estado):
        if estado != 302:
            if estado not in (200, 401, 403):
                # Incluye 429 y 5xx sin reintentos ni datos de encabezados/cuerpo.
                raise SigacClientError(
                    "Respuesta HTTP inesperada durante el acceso.",
                    codigo=CodigoHistorial.HTTP_INESPERADO,
                    diagnostico=diagnostico_seguro(CodigoHistorial.HTTP_INESPERADO,
                                                   {"http_estado": estado}, etapa=self.contexto.etapa),
                )
            raise SigacSessionExpired("No se confirmó el acceso; no se reintentará automáticamente.",
                                      codigo=CodigoHistorial.AUTENTICACION_NO_CONFIRMADA)

    def observar_redireccion_login(self, usuario, clave, *, tipo, caso_login=None):
        """A lo sumo un GET y un POST. No confirma sesión ni consulta recursos.

        Usar desde la entrada dedicada, que bloquea los logs de bibliotecas.
        Limpia cookies incluso si falla o se interrumpe antes del resultado.
        """
        self.contexto.marcar(EtapaSigac.PREPARACION)
        self._invalidar()
        try:
            if not all(isinstance(v, str) and v for v in (usuario, clave, tipo)):
                raise SigacClientError("Faltan datos explícitos para el acceso.",
                                       codigo=CodigoHistorial.ACCESO_INCOMPLETO)
            estado, cabeceras, _ = self._enviar_login(usuario, clave, tipo=tipo, caso_login=caso_login)
            self._verificar_estado_login(estado)
            self.contexto.marcar(EtapaSigac.REDIRECCION_LOGIN)
            return observar_destino_login(cabeceras).diagnostico()
        except RespuestaIncompleta as error:
            raise SigacClientError("La respuesta no cumple el contrato de observación.",
                                   codigo=error.codigo, etapa=self.contexto.etapa) from None
        except SigacClientError as error:
            self._anotar_error(error)
            raise
        finally:
            self._invalidar()

    def autenticar(self, usuario, clave, *, tipo, total_casos_esperado, caso_login=None, listado_estructural=False):
        """Credenciales temporales, nunca en atributos ni logs.

        tipo es un valor de cboTipo elegido expresamente. cmdIngresar y txtCaso
        proceden del formulario. El total se contrasta con el listado completo
        verificado por el operador; no hay reintentos automáticos.
        """
        self.contexto.marcar(EtapaSigac.PREPARACION)
        self._invalidar()
        if not all(isinstance(v, str) and v for v in (usuario, clave, tipo)):
            raise SigacClientError("Faltan datos explícitos para el acceso.",
                                   codigo=CodigoHistorial.ACCESO_INCOMPLETO, etapa=self.contexto.etapa)
        # `listado_estructural=True` es una opción explícita (sin total fijo): se mantienen todas las verificaciones
        # de estructura del listado y la identidad del expediente; solo se omite la igualdad con un total externo.
        if listado_estructural:
            total_valido = total_casos_esperado is None
        else:
            total_valido = type(total_casos_esperado) is int and total_casos_esperado >= 0
        if not total_valido:
            raise SigacClientError("Falta el total completo del listado contrastado.",
                                   codigo=CodigoHistorial.ENTRADA_INVALIDA, etapa=self.contexto.etapa)
        completado = False
        try:
            estado, cabeceras, _ = self._enviar_login(usuario, clave, tipo=tipo, caso_login=caso_login)
            self._verificar_estado_login(estado)
            self.contexto.marcar(EtapaSigac.REDIRECCION_LOGIN)
            ruta = destino_login_confirmado(cabeceras)
            self.contexto.marcar(EtapaSigac.SESION)
            selector = "general.formCambiarTipoUsuario.con"
            if not self._tiene_cookie(ruta) or not self._tiene_cookie(selector):
                raise SigacSessionExpired("No existe una sesión HTTP válida para continuar.",
                                          codigo=CodigoHistorial.SESION_NO_CONFIRMADA)
            self.contexto.marcar(EtapaSigac.SELECTOR_ROL)
            # Incluso si login apunta a principal, exigir selección explícita.
            verificar_selector_estudiante(self._html(self._solicitar("GET", selector), permitir_selector=True))
            destino = self.seleccionar_rol(RolSigac.ESTUDIANTE)
            self.contexto.marcar(EtapaSigac.PRINCIPAL)
            pagina_protegida(self.obtener_html(destino))
            # Ni el 302, ni la cookie, ni la principal acreditan por sí solos acceso.
            self.contexto.marcar(EtapaSigac.LISTADO_INICIAL)
            casos = self._leer_listado(total_casos_esperado, estructural=listado_estructural)
            self._confirmada = True
            completado = True
            return casos
        except RespuestaIncompleta as error:
            raise SigacClientError("El formulario o la respuesta no cumplen el contrato confirmado.",
                                   codigo=error.codigo, etapa=self.contexto.etapa) from None
        except SigacClientError as error:
            self._anotar_error(error)
            raise
        finally:
            # También limpia ante advertencias, errores internos e interrupción.
            if not completado:
                self._invalidar()

    def _leer_listado(self, total_esperado, estructural=False):
        if not self._tiene_cookie(LISTADO):
            raise SigacSessionExpired("Falta una sesión HTTP válida.")
        html = self.obtener_html(LISTADO)
        try:
            pagina_protegida(html)
            casos = extraer_casos(html, estricto=True, total_esperado=total_esperado, estructural=estructural)
        except RespuestaIncompleta as error:
            self._casos.clear()
            raise SigacClientError("Listado incompleto, ambiguo o distinto del total contrastado.",
                                   codigo=error.codigo, etapa=self.contexto.etapa) from None
        except ValueError:
            self._casos.clear()
            raise SigacClientError("Listado incompleto, ambiguo o distinto del total contrastado.",
                                   codigo=CodigoHistorial.LISTADO_NO_CONFIRMADO, etapa=self.contexto.etapa) from None
        if not self._tiene_cookie(LISTADO):
            raise SigacSessionExpired("La sesión dejó de estar disponible durante la consulta.")
        self._casos = {c.numero for c in casos}
        return casos

    def listar_casos(self, *, total_esperado):
        self.contexto.marcar(EtapaSigac.LISTADO_REPETIDO)
        if not self.autenticada:
            raise SigacSessionExpired("Se requiere autenticación confirmada.")
        try:
            return self._leer_listado(total_esperado)
        except SigacClientError as error:
            self._anotar_error(error)
            self._invalidar()
            raise

    def consultar_historial(self, numero, *, total_esperado=None, contenedor_id=None, diagnostico=False):
        if self.contexto.etapa not in (EtapaSigac.HISTORIAL_INICIAL, EtapaSigac.HISTORIAL_REPETIDO):
            self.contexto.marcar(EtapaSigac.HISTORIAL)
        if not self.autenticada:
            raise SigacSessionExpired("Se requiere autenticación confirmada.")
        if type(numero) is not int or numero not in self._casos:
            raise SigacClientError("El expediente no pertenece al último listado validado.",
                                   codigo=CodigoHistorial.EXPEDIENTE_NO_LISTADO, etapa=self.contexto.etapa)
        if total_esperado is not None and (type(total_esperado) is not int or total_esperado < 1):
            raise SigacClientError("El total histórico opcional debe ser un entero positivo.",
                                   codigo=CodigoHistorial.ENTRADA_INVALIDA, etapa=self.contexto.etapa)
        conteos = {}
        try:
            html = self._html(self._solicitar("POST", "casos.formCaso.con", datos={
                "hidCaso": str(numero), "hidMotivo": "ACTUAR_ESTUDIANTE",
            }))
            if diagnostico:
                conteos.update(estadisticas_documento(html))
            pagina_protegida(html)
            detalle = validar_detalle(html, numero)
            completas = parse_actuaciones(html, str(numero), estadisticas=conteos)
            actuaciones = parse_actuaciones(detalle, str(numero))
            if completas != actuaciones:
                raise ErrorIdentidadRespuesta(fuera=True)
            if contenedor_id is not None:
                acotadas = parse_actuaciones(detalle, str(numero), contenedor_id=contenedor_id)
                if acotadas != actuaciones:
                    raise ErrorIdentidadRespuesta(fuera=True)
            if not actuaciones:
                raise RespuestaIncompleta("No se pudo reconocer un historial.", codigo=CodigoHistorial.SIN_ACTUACIONES)
            if total_esperado is not None and len(actuaciones) != total_esperado:
                raise RespuestaIncompleta("El total histórico no coincide.", codigo=CodigoHistorial.TOTAL_DISCORDANTE)
            # Solo dos enteros de la última consulta correcta, para el resumen del ensayo.
            self.ultimo_conteo_interactivo = {
                clave: conteos.get(clave) for clave in ("regiones_interactivas_excluidas", "filas_interactivas_excluidas")
            }
            return HistorialSigac(actuaciones)
        except ErrorIdentidadRespuesta as error:
            self._invalidar()
            raise SigacIdentityError("Consistencia de identidad o ámbito histórico no confirmados.",
                                     codigo=error.codigo, etapa=self.contexto.etapa,
                                     diagnostico=diagnostico_seguro(error.codigo, conteos, etapa=self.contexto.etapa)
                                     if diagnostico else None) from None
        except (RespuestaIncompleta, ErrorParseoHistorial) as error:
            raise SigacClientError("Historial incompleto, ambiguo o de estructura no confirmada.",
                                   codigo=error.codigo, etapa=self.contexto.etapa,
                                   diagnostico=diagnostico_seguro(error.codigo, conteos, etapa=self.contexto.etapa)
                                   if diagnostico else None) from None
        except SigacClientError as error:
            self._anotar_error(error)
            raise

    def cerrar(self):
        self._invalidar()
        if self._owns_client:
            self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        anterior = self.contexto.etapa
        self.contexto.marcar(EtapaSigac.CIERRE)
        self.cerrar()
        if exc_type is not None:
            self.contexto.marcar(anterior)
