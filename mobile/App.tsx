import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import Acceso from './src/Acceso';
import Principal from './src/Principal';
import { Boton } from './src/componentes';
import { biometriaActiva, borrarToken, desbloquear, fijarBiometria, guardarToken, leerToken } from './src/almacen';
import { colores } from './src/tema';

type Fase = 'cargando' | 'bloqueada' | 'acceso' | 'principal';

export default function App() {
  const [fase, setFase] = useState<Fase>('cargando');
  const [token, setToken] = useState<string>();
  const [biometria, setBiometria] = useState(false);
  const version = Constants.expoConfig?.version ?? '0.1.0';

  const intentarDesbloqueo = useCallback(async () => { if (await desbloquear()) setFase('principal'); }, []);

  useEffect(() => {
    void (async () => {
      const guardado = await leerToken();
      const bio = await biometriaActiva();
      setBiometria(bio);
      if (!guardado) { setFase('acceso'); return; }
      setToken(guardado);
      if (bio) { setFase('bloqueada'); await intentarDesbloqueo(); } else setFase('principal');
    })();
  }, [intentarDesbloqueo]);

  async function alConectar(nuevo: string) { await guardarToken(nuevo); setToken(nuevo); setFase('principal'); }
  const salir = useCallback(async () => { await borrarToken(); await fijarBiometria(false); setToken(undefined); setBiometria(false); setFase('acceso'); }, []);
  async function cambiarBiometria(activa: boolean) {
    if (activa && !(await desbloquear())) return;  // se confirma antes de activar
    await fijarBiometria(activa); setBiometria(activa);
  }

  return <View style={{ flex: 1, backgroundColor: colores.fondo }}>
    <StatusBar style="dark" />
    {fase === 'cargando' && <View style={{ flex: 1, justifyContent: 'center' }}><ActivityIndicator size="large" color={colores.marino} /></View>}
    {fase === 'bloqueada' && <View style={{ flex: 1, justifyContent: 'center', padding: 32, gap: 16 }}>
      <Text style={{ fontSize: 30, fontWeight: '700', color: colores.texto, textAlign: 'center' }}>Tinotify</Text>
      <Text style={{ fontSize: 16, color: colores.textoSuave, textAlign: 'center' }}>Confirma tu identidad para continuar.</Text>
      <Boton texto="Desbloquear" icono="finger-print" onPress={() => { void intentarDesbloqueo(); }} />
    </View>}
    {fase === 'acceso' && <Acceso onListo={alConectar} />}
    {fase === 'principal' && token && <Principal token={token} biometria={biometria} version={version} onBiometria={cambiarBiometria} onSalir={salir} />}
  </View>;
}
