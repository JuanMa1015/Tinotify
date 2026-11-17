const PREDETERMINADA = 'https://tinotify.onrender.com';

// Solo HTTPS, sin credenciales, ruta ni parámetros. En desarrollo se permite http solo hacia la propia máquina.
export function urlValida(valor: string, desarrollo = false): string {
  let u: URL;
  try { u = new URL(valor); } catch { throw new Error('URL del servidor no válida'); }
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname);
  const protocoloOk = u.protocol === 'https:' || (desarrollo && local && u.protocol === 'http:');
  if (!protocoloOk || u.username || u.password || u.search || u.hash || u.pathname !== '/') {
    throw new Error('La URL del servidor debe ser HTTPS, sin credenciales ni parámetros');
  }
  return u.origin;
}

export const baseURL = urlValida(process.env.EXPO_PUBLIC_API_URL ?? PREDETERMINADA, typeof __DEV__ !== 'undefined' && __DEV__);
