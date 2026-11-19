import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';

// El token de acceso al servidor vive solo en el almacén seguro de Android. Usuario y clave de SIGAC NUNCA se guardan en el teléfono.
const CLAVE_TOKEN = 'tinotify.token.v1';
const CLAVE_BIOMETRIA = 'tinotify.biometria.v1';

export const leerToken = () => SecureStore.getItemAsync(CLAVE_TOKEN);
export const guardarToken = (token: string) => SecureStore.setItemAsync(CLAVE_TOKEN, token);
export const borrarToken = () => SecureStore.deleteItemAsync(CLAVE_TOKEN);

export async function biometriaActiva(): Promise<boolean> { return (await SecureStore.getItemAsync(CLAVE_BIOMETRIA)) === '1'; }
export async function fijarBiometria(activa: boolean): Promise<void> {
  if (activa) await SecureStore.setItemAsync(CLAVE_BIOMETRIA, '1'); else await SecureStore.deleteItemAsync(CLAVE_BIOMETRIA);
}

export async function biometriaDisponible(): Promise<boolean> {
  return (await LocalAuthentication.hasHardwareAsync()) && (await LocalAuthentication.isEnrolledAsync());
}

// Huella o rostro, con el PIN del teléfono como alternativa (para que un sensor dañado no deje fuera al usuario).
export async function desbloquear(): Promise<boolean> {
  const r = await LocalAuthentication.authenticateAsync({ promptMessage: 'Abrir Tinotify', cancelLabel: 'Cancelar', disableDeviceFallback: false });
  return r.success;
}

// El correo se guarda solo para mostrarlo en Ajustes (el servidor ya lo conoce); nunca la contraseña.
const CLAVE_CORREO = 'tinotify.correo.v1';
export const leerCorreo = () => SecureStore.getItemAsync(CLAVE_CORREO);
export const guardarCorreo = (correo: string) => SecureStore.setItemAsync(CLAVE_CORREO, correo);
export const borrarCorreo = () => SecureStore.deleteItemAsync(CLAVE_CORREO);

// Nombre con el que la aplicación te saluda: lo escribes tú, vive solo en este teléfono y nunca se envía al servidor.
const CLAVE_NOMBRE = 'tinotify.nombre.v1';
// Nombre tomado de SIGAC (también solo en este teléfono) y cuándo se intentó leerlo, para no repetir el intento a cada apertura.
const CLAVE_NOMBRE_SIGAC = 'tinotify.nombre-sigac.v1';
export async function leerNombreSigac(): Promise<{ nombre: string; intento: number } | null> {
  try {
    const j = JSON.parse((await SecureStore.getItemAsync(CLAVE_NOMBRE_SIGAC)) ?? 'null') as { nombre?: unknown; intento?: unknown } | null;
    return j && typeof j.nombre === 'string' && typeof j.intento === 'number' ? { nombre: j.nombre, intento: j.intento } : null;
  } catch { return null; }
}
export const guardarNombreSigac = (nombre: string, intento: number) => SecureStore.setItemAsync(CLAVE_NOMBRE_SIGAC, JSON.stringify({ nombre, intento }));
export const borrarNombres = async () => { await SecureStore.deleteItemAsync(CLAVE_NOMBRE_SIGAC); await SecureStore.deleteItemAsync('tinotify.nombre.v1'); };
export const leerNombre = () => SecureStore.getItemAsync(CLAVE_NOMBRE);
export const guardarNombre = (nombre: string) => (nombre === '' ? SecureStore.deleteItemAsync(CLAVE_NOMBRE) : SecureStore.setItemAsync(CLAVE_NOMBRE, nombre));
