import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';
import { quitarDispositivo, registrarDispositivo } from './api';

const CLAVE_FCM = 'tinotify.fcm.v1';

Notifications.setNotificationHandler({ handleNotification: async () => ({
  shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
}) });

export async function activarPush(tokenApp: string): Promise<'ok' | 'permiso_denegado'> {
  await Notifications.setNotificationChannelAsync('avisos', { name: 'Avisos de SIGAC', importance: Notifications.AndroidImportance.HIGH });
  let permiso = await Notifications.getPermissionsAsync();
  if (permiso.status !== 'granted') permiso = await Notifications.requestPermissionsAsync();
  if (permiso.status !== 'granted') return 'permiso_denegado';
  const dispositivo = await Notifications.getDevicePushTokenAsync();  // token FCM nativo (no el de Expo)
  const fcm = String(dispositivo.data);
  await registrarDispositivo(tokenApp, fcm);
  await SecureStore.setItemAsync(CLAVE_FCM, fcm);
  return 'ok';
}

export async function desactivarPush(tokenApp: string): Promise<void> {
  const fcm = await SecureStore.getItemAsync(CLAVE_FCM);
  if (fcm) { try { await quitarDispositivo(tokenApp, fcm); } catch { /* el servidor lo limpia si FCM lo rechaza */ } }
  await SecureStore.deleteItemAsync(CLAVE_FCM);
}

export const pushActivo = async (): Promise<boolean> => (await SecureStore.getItemAsync(CLAVE_FCM)) !== null;

export type Pestana = 'inicio' | 'casos' | 'actividad' | 'ajustes';
const PESTANAS: Pestana[] = ['inicio', 'casos', 'actividad', 'ajustes'];

/** Pestaña que debe abrir la app al tocar una notificación (el servidor la envía en `data.pestana`; nunca datos del caso). */
export function pestanaDeNotificacion(respuesta: Notifications.NotificationResponse | null): Pestana | null {
  const dato = respuesta?.notification.request.content.data?.pestana;
  return typeof dato === 'string' && (PESTANAS as string[]).includes(dato) ? (dato as Pestana) : null;
}
