import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { nombreSeguro } from './archivos';
import { baseURL } from './config';
import { CONSENTIMIENTO, esTokenDeUsuario } from './cuentas';
import type { Ejecucion, EstadoMonitor } from './revisiones';

export class ErrorApi extends Error {
  constructor(mensaje: string, readonly estado: number | null, readonly detalle?: string) { super(mensaje); }
}

const MENSAJES: Record<number, string> = {
  401: 'El código de acceso no es válido.',
  403: 'El servidor rechazó la conexión.',
  409: 'Ya hay un acceso en curso. Espera un momento.',
  412: 'No hay credenciales guardadas.',
  422: 'SIGAC no devolvió lo esperado para esta cuenta.',
  429: 'Demasiados intentos. Espera unos minutos.',
  502: 'SIGAC no aceptó los datos o no respondió.',
  503: 'El servicio no está disponible. Inténtalo en un momento.',
};

async function solicitar<T>(ruta: string, token: string | undefined, opciones: { metodo?: string; cuerpo?: unknown; limiteMs?: number } = {}): Promise<T> {
  const cancelar = new AbortController();
  const temporizador = setTimeout(() => cancelar.abort(), opciones.limiteMs ?? 30000);
  try {
    const r = await fetch(`${baseURL}${ruta}`, {
      method: opciones.metodo ?? (opciones.cuerpo === undefined ? 'GET' : 'POST'),
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: opciones.cuerpo === undefined ? undefined : JSON.stringify(opciones.cuerpo),
      signal: cancelar.signal,
    });
    if (!r.ok) {
      let detalle: string | undefined;
      try { const j = await r.json() as { detail?: unknown }; if (typeof j.detail === 'string') detalle = j.detail; } catch { /* sin cuerpo */ }
      throw new ErrorApi(MENSAJES[r.status] ?? 'No se completó la operación.', r.status, detalle);
    }
    return (r.status === 204 ? undefined : await r.json()) as T;
  } catch (e) {
    if (e instanceof ErrorApi) throw e;
    throw new ErrorApi('Sin conexión con el servidor. El primer intento puede tardar hasta un minuto; reintenta.', null);
  } finally { clearTimeout(temporizador); }
}

// Login: el servidor (Render) arranca en frío y lee SIGAC, puede tardar 2-3 minutos.
export async function conectar(token: string, usuario: string, clave: string): Promise<void> {
  if (esTokenDeUsuario(token)) {  // cuenta de usuario: el servidor comprueba con SIGAC y guarda las credenciales cifradas
    await solicitar('/real/conectar', token, { cuerpo: { usuario, clave }, limiteMs: 200000 });
    return;
  }
  await solicitar('/real/sesion', token, { cuerpo: { usuario, clave, recordar: true }, limiteMs: 200000 });
  try { await solicitar('/real/sesion', token, { metodo: 'DELETE' }); } catch { /* la sesión temporal expira sola */ }
}

export const obtenerEstado = (token: string) => solicitar<EstadoMonitor>('/real/monitor/estado', token, { limiteMs: 90000 });
export const olvidarCredenciales = (token: string) => solicitar<{ credenciales_guardadas: boolean }>('/real/credenciales', token, { metodo: 'DELETE' });

export const registrarDispositivo = (token: string, fcm: string) => solicitar<{ registrado: boolean }>('/real/dispositivos', token, { cuerpo: { token: fcm } });
export const quitarDispositivo = (token: string, fcm: string) => solicitar<{ borrado: boolean }>('/real/dispositivos', token, { metodo: 'DELETE', cuerpo: { token: fcm } });

export const obtenerEjecuciones = (token: string) => solicitar<{ ejecuciones: Ejecucion[] }>('/real/monitor/ejecuciones?limite=30', token, { limiteMs: 90000 });

export type Expediente = { id: string; numero: number; cliente: string; estado: string; novedades_no_vistas: number; nuevo: boolean; ultima_novedad: string | null };
export const obtenerExpedientes = (token: string) => solicitar<{ expedientes: Expediente[] }>('/real/expedientes', token, { limiteMs: 90000 });
export const marcarVistos = (token: string, id?: string) => solicitar<{ actualizados: number }>('/real/expedientes/vistos', token, { cuerpo: id ? { id } : {} });
export const enviarPrueba = (token: string) => solicitar<{ enviados: number; invalidos: number }>('/real/dispositivos/prueba', token, { cuerpo: {}, limiteMs: 60000 });

export type Actuacion = {
  fecha: string; etapa: string; origen: string; destino: string; remitente: string; descripcion: string;
  anexos: { descripcion: string; archivo: string; sin_enlace: boolean; con_enlace?: boolean }[];
};
// Lee SIGAC en ese momento a través del servidor (inicia sesión con tus credenciales guardadas): puede tardar hasta un minuto.
export const obtenerActuaciones = (token: string, id: string) =>
  solicitar<{ actuaciones: Actuacion[] }>(`/real/expedientes/${id}/actuaciones`, token, { limiteMs: 150000 });

// --- Cuentas de usuario (registro por invitación) ---
export type SesionNueva = { token: string; usuario: string };
export const registrar = (d: { invitacion: string; correo: string; clave: string }) =>
  solicitar<SesionNueva>('/auth/registro', undefined, { cuerpo: { ...d, consentimiento: CONSENTIMIENTO, dispositivo: 'Android' }, limiteMs: 60000 });
export const iniciarSesion = (correo: string, clave: string) =>
  solicitar<SesionNueva>('/auth/login', undefined, { cuerpo: { correo, clave, dispositivo: 'Android' }, limiteMs: 60000 });
export const cerrarSesionEnServidor = (token: string) => solicitar<{ cerrada: boolean }>('/auth/logout', token, { cuerpo: {} });
export const cambiarClave = (token: string, actual: string, nueva: string) => solicitar<{ cambiada: boolean }>('/auth/cambiar-clave', token, { cuerpo: { actual, nueva } });
export const eliminarCuenta = (token: string, clave: string) => solicitar<{ borrada: boolean }>('/auth/cuenta', token, { metodo: 'DELETE', cuerpo: { clave } });
export const crearInvitacion = (token: string) => solicitar<{ codigo: string; vigencia_dias: number }>('/auth/invitaciones', token, { cuerpo: {} });

/** Baja un anexo a través del servidor (que lo pide a SIGAC con tus credenciales; no se guarda allí) y abre el menú para verlo o compartirlo. */
export async function descargarAnexo(token: string, id: string, actuacion: number, anexo: number, nombre: string): Promise<void> {
  const destino = `${FileSystem.cacheDirectory}${nombreSeguro(nombre)}`;
  let r: FileSystem.FileSystemDownloadResult;
  try {
    r = await FileSystem.downloadAsync(`${baseURL}/real/expedientes/${id}/actuaciones/${actuacion}/anexos/${anexo}`, destino,
      { headers: { Authorization: `Bearer ${token}` } });
  } catch { throw new ErrorApi('Sin conexión con el servidor. Reintenta en un momento.', null); }
  if (r.status !== 200) {
    await FileSystem.deleteAsync(destino, { idempotent: true });
    throw new ErrorApi(r.status === 404 ? 'El anexo ya no está disponible: cierra el expediente y ábrelo de nuevo.' :
      r.status === 429 ? 'Demasiados intentos. Espera unos minutos.' : r.status === 409 ? 'Ya hay un acceso en curso. Espera un momento.' :
      r.status === 502 || r.status === 503 ? 'SIGAC no entregó el archivo. Inténtalo de nuevo o ábrelo en SIGAC.' : 'No se pudo descargar el anexo.', r.status);
  }
  if (!(await Sharing.isAvailableAsync())) throw new ErrorApi('Este teléfono no puede abrir archivos desde la aplicación.', null);
  await Sharing.shareAsync(r.uri, { dialogTitle: nombre });
}
