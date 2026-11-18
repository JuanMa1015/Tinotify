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
