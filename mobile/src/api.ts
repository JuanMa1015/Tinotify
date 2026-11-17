import { baseURL } from './config';
import type { EstadoMonitor } from './revisiones';

export class ErrorApi extends Error {
  constructor(mensaje: string, readonly estado: number | null) { super(mensaje); }
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

async function solicitar<T>(ruta: string, token: string, opciones: { metodo?: string; cuerpo?: unknown; limiteMs?: number } = {}): Promise<T> {
  const cancelar = new AbortController();
  const temporizador = setTimeout(() => cancelar.abort(), opciones.limiteMs ?? 30000);
  try {
    const r = await fetch(`${baseURL}${ruta}`, {
      method: opciones.metodo ?? (opciones.cuerpo === undefined ? 'GET' : 'POST'),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: opciones.cuerpo === undefined ? undefined : JSON.stringify(opciones.cuerpo),
      signal: cancelar.signal,
    });
    if (!r.ok) throw new ErrorApi(MENSAJES[r.status] ?? 'No se completó la operación.', r.status);
    return (r.status === 204 ? undefined : await r.json()) as T;
  } catch (e) {
    if (e instanceof ErrorApi) throw e;
    throw new ErrorApi('Sin conexión con el servidor. El primer intento puede tardar hasta un minuto; reintenta.', null);
  } finally { clearTimeout(temporizador); }
}

// Login: el servidor (Render) arranca en frío y lee SIGAC, puede tardar 2-3 minutos.
export async function conectar(token: string, usuario: string, clave: string): Promise<void> {
  await solicitar('/real/sesion', token, { cuerpo: { usuario, clave, recordar: true }, limiteMs: 200000 });
  try { await solicitar('/real/sesion', token, { metodo: 'DELETE' }); } catch { /* la sesión temporal expira sola */ }
}

export const obtenerEstado = (token: string) => solicitar<EstadoMonitor>('/real/monitor/estado', token, { limiteMs: 90000 });
export const olvidarCredenciales = (token: string) => solicitar<{ credenciales_guardadas: boolean }>('/real/credenciales', token, { metodo: 'DELETE' });
