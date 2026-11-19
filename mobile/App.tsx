import { useCallback, useEffect, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import Acceso from './src/Acceso';
import { Bienvenida, Login, Registro } from './src/AuthPantallas';
import Principal from './src/Principal';
import { Boton, PantallaCarga } from './src/componentes';
import { cerrarSesionEnServidor, obtenerEstado, obtenerYo } from './src/api';
import { biometriaActiva, biometriaDisponible, borrarCorreo, borrarNombres, borrarToken, desbloquear, fijarBiometria, guardarCorreo, guardarToken, huellaOfrecida, leerCorreo, leerToken, marcarHuellaOfrecida } from './src/almacen';
import { esTokenDeUsuario } from './src/cuentas';
import { destinoDeNotificacion, type Destino } from './src/notificaciones';
import { colores } from './src/tema';

type Fase = 'cargando' | 'bloqueada' | 'bienvenida' | 'login' | 'registro' | 'propietario' | 'conectar' | 'principal';

export default function App() {
  const [fase, setFase] = useState<Fase>('cargando');
  const [token, setToken] = useState<string>();
  const [biometria, setBiometria] = useState(false);
  const [destino, setDestino] = useState<Destino | null>(null);
  const [correo, setCorreo] = useState<string>();
  const version = Constants.expoConfig?.version ?? '0.1.0';

  const intentarDesbloqueo = useCallback(async () => { if (await desbloquear()) setFase('principal'); }, []);

  useEffect(() => {
    void (async () => {
      const guardado = await leerToken();
      const bio = await biometriaActiva();
      setBiometria(bio);
      setCorreo((await leerCorreo()) ?? undefined);
      if (!guardado) { setFase('bienvenida'); return; }
      setToken(guardado);
      if (bio) { setFase('bloqueada'); await intentarDesbloqueo(); } else setFase('principal');
    })();
  }, [intentarDesbloqueo]);

  useEffect(() => {  // tocar una notificación abre la pestaña indicada (también con la app cerrada)
    const abrir = (r: Notifications.NotificationResponse | null) => { const d = destinoDeNotificacion(r); if (d) setDestino(d); };
    abrir(Notifications.getLastNotificationResponse());
    const escucha = Notifications.addNotificationResponseReceivedListener(abrir);
    return () => escucha.remove();
  }, []);

  // Tras la primera entrada en este teléfono se ofrece la huella (una sola vez) para que las siguientes aperturas no pidan nada más.
  async function ofrecerHuella() {
    try {
      if ((await huellaOfrecida()) || (await biometriaActiva()) || !(await biometriaDisponible())) return;
      await marcarHuellaOfrecida();
      Alert.alert('¿Abrir Tinotify con tu huella o rostro?', 'Así no tendrás que pedir un código cada vez que abras la aplicación. Puedes cambiarlo después en Ajustes → Seguridad.', [
        { text: 'Ahora no', style: 'cancel' },
        { text: 'Activar', onPress: () => { void cambiarBiometria(true); } },
      ]);
    } catch { /* la huella es opcional */ }
  }

  // Tras registrarse o entrar: una cuenta administradora va directo a su panel; una de seguimiento conecta SIGAC si aún no lo ha hecho.
  async function alAutenticar(nuevo: string, esRegistro: boolean, correoNuevo?: string) {
    await guardarToken(nuevo); setToken(nuevo);
    if (correoNuevo) { await guardarCorreo(correoNuevo); setCorreo(correoNuevo); }
    void ofrecerHuella();
    if (esRegistro) { setFase('conectar'); return; }
    try {
      const yo = await obtenerYo(nuevo);
      if (yo.admin) { setFase('principal'); return; }
      setFase((await obtenerEstado(nuevo)).credenciales_guardadas ? 'principal' : 'conectar');
    } catch { setFase('principal'); }
  }
  async function alConectarPropietario(nuevo: string) { await guardarToken(nuevo); setToken(nuevo); setFase('principal'); }

  const salir = useCallback(async () => {
    const actual = token;
    if (actual && esTokenDeUsuario(actual)) { try { await cerrarSesionEnServidor(actual); } catch { /* la sesión caduca sola */ } }
    await borrarToken(); await borrarCorreo(); await borrarNombres().catch(() => undefined); await fijarBiometria(false);
    setToken(undefined); setCorreo(undefined); setBiometria(false); setFase('bienvenida');
  }, [token]);

  async function cambiarBiometria(activa: boolean) {
    if (activa && !(await desbloquear())) return;  // se confirma antes de activar
    await fijarBiometria(activa); setBiometria(activa);
  }

  return <View style={{ flex: 1, backgroundColor: colores.fondo }}>
    <StatusBar style="dark" />
    {fase === 'cargando' && <PantallaCarga />}
    {fase === 'bloqueada' && <View style={{ flex: 1, justifyContent: 'center', padding: 32, gap: 16 }}>
      <Text style={{ fontSize: 30, fontWeight: '700', color: colores.texto, textAlign: 'center' }}>Tinotify</Text>
      <Text style={{ fontSize: 16, color: colores.textoSuave, textAlign: 'center' }}>Confirma tu identidad para continuar.</Text>
      <Boton texto="Desbloquear" icono="finger-print" onPress={() => { void intentarDesbloqueo(); }} />
    </View>}
    {fase === 'bienvenida' && <Bienvenida onLogin={() => setFase('login')} onRegistro={() => setFase('registro')} onPropietario={() => setFase('propietario')} />}
    {fase === 'login' && <Login onListo={(t, c) => alAutenticar(t, false, c)} onVolver={() => setFase('bienvenida')} />}
    {fase === 'registro' && <Registro onListo={(t, c) => alAutenticar(t, true, c)} onVolver={() => setFase('bienvenida')} />}
    {fase === 'propietario' && <Acceso onListo={alConectarPropietario} onCancelar={() => setFase('bienvenida')} />}
    {fase === 'conectar' && token && <Acceso tokenFijo={token} titulo="Conecta tu cuenta de SIGAC" onListo={async () => setFase('principal')} onCancelar={() => setFase('principal')} />}
    {fase === 'principal' && token && <Principal token={token} correo={correo} biometria={biometria} version={version} onBiometria={cambiarBiometria} onSalir={salir} destino={destino} onDestinoAtendido={() => setDestino(null)} />}
  </View>;
}
