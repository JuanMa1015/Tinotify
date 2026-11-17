import type { ExpoConfig } from 'expo/config';

const projectId = '53e7a921-b20c-4983-8c40-e4db0d3fd203';

const config: ExpoConfig = {
  name: 'Tinotify',
  slug: 'tinotify-demo',
  version: '0.1.0',
  orientation: 'portrait',
  scheme: 'tinotify',
  userInterfaceStyle: 'light',
  icon: './assets/icon.png',
  owner: process.env.EXPO_OWNER,
  android: {
    package: 'com.tinotify.app',
    allowBackup: false,
    googleServicesFile: process.env.GOOGLE_SERVICES_JSON,  // variable de tipo archivo en EAS; nunca en el repositorio
    adaptiveIcon: { foregroundImage: './assets/icon-foreground.png', backgroundColor: '#0C1D40' },
  },
  plugins: [
    ['expo-splash-screen', { image: './assets/splash-icon.png', imageWidth: 200, backgroundColor: '#D9E4F4' }],
    ['expo-notifications', { color: '#14213D' }],
    'expo-secure-store',
    ['expo-local-authentication', { faceIDPermission: 'Tinotify usa tu huella o rostro para abrir la app.' }],
  ],
  extra: { eas: { projectId } },
};

export default config;
