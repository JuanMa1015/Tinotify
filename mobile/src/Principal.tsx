import { useCallback, useEffect, useState } from 'react';
import { Alert, Image, RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Aviso, BarraInferior, Boton, Etiqueta, Tarjeta, Titulo } from './componentes';
import { ErrorApi, obtenerEstado, olvidarCredenciales } from './api';
import { biometriaDisponible } from './almacen';
import { horaBogota, proximaRevision, resumenDeEstado, type EstadoMonitor } from './revisiones';
import { colores, espacio } from './tema';

type Props = {
  token: string; biometria: boolean; version: string;
  onBiometria: (activa: boolean) => Promise<void>; onSalir: () => Promise<void>;
};

export default function Principal({ token, biometria, version, onBiometria, onSalir }: Props) {
  const [pestana, setPestana] = useState('inicio');
  const [estado, setEstado] = useState<EstadoMonitor>();
  const [error, setError] = useState('');
  const [refrescando, setRefrescando] = useState(false);

  const cargar = useCallback(async () => {
    setRefrescando(true);
    try { setEstado(await obtenerEstado(token)); setError(''); }
    catch (err) {
      setError(err instanceof ErrorApi ? err.message : 'No se pudo actualizar.');
      if (err instanceof ErrorApi && err.estado === 401) await onSalir();
    } finally { setRefrescando(false); }
  }, [token, onSalir]);

  useEffect(() => { void cargar(); }, [cargar]);

  const resumen = estado ? resumenDeEstado(estado) : undefined;
  const proxima = proximaRevision(new Date());

  return <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} refreshControl={<RefreshControl refreshing={refrescando} onRefresh={() => { void cargar(); }} tintColor={colores.marino} />}>
      {error !== '' && <Aviso texto={error} />}
      <Image source={require('../assets/huellas.png')} accessible={false} resizeMode="contain" style={s.huellas} />
      {pestana === 'inicio' && <>
        <Titulo texto={'Buenos\ndías'} />
        <Tarjeta oscura estilo={{ overflow: 'hidden' }}>
          <Image source={require('../assets/gato-ojos.png')} accessible={false} resizeMode="contain" style={s.ojos} />
          <Text style={s.claro}><Ionicons name="calendar-outline" size={14} /> Última revisión</Text>
          <Text style={s.grande}>
            {estado?.ultima_ejecucion ? `${horaBogota(estado.ultima_ejecucion.inicio)} · ${resumen?.titulo}` : resumen?.titulo ?? 'Cargando…'}
          </Text>
          {resumen && <Text style={s.claro}>{resumen.detalle}</Text>}
          <View style={s.chips}>
            <Etiqueta texto={`Próxima ${proxima.etiqueta}`} tono="azul" />
            {resumen && <Etiqueta texto={resumen.requiereAtencion ? 'Requiere atención' : 'Sin errores'} tono={resumen.requiereAtencion ? 'rojo' : 'lima'} />}
          </View>
        </Tarjeta>
        <Tarjeta>
          <View style={s.cifras}>
            <Cifra icono="folder-outline" valor={estado?.expedientes_en_estado} texto="Expedientes" />
            <Cifra icono="refresh-outline" valor={3} texto="Revisiones/día" />
            <Cifra icono="notifications-outline" valor={estado?.avisos_pendientes} texto="Avisos" />
          </View>
        </Tarjeta>
      </>}
      {pestana === 'casos' && <>
        <Titulo texto="Expedientes" subtitulo={estado ? `${estado.expedientes_en_estado} en seguimiento` : undefined} />
        <Tarjeta>
          <Text style={s.cuerpo}>Tinotify vigila todos los expedientes de tu cuenta de SIGAC. Por privacidad, el servidor no guarda números ni contenido de tus casos, solo huellas cifradas para detectar cambios.</Text>
          <Text style={[s.cuerpo, { marginTop: 8 }]}>El detalle por expediente llegará en una próxima versión.</Text>
        </Tarjeta>
      </>}
      {pestana === 'actividad' && <>
        <Titulo texto="Actividad" />
        <Tarjeta>
          {estado?.ultima_ejecucion
            ? <><Text style={s.fuerte}>{resumen?.titulo}</Text><Text style={s.cuerpo}>Revisión de las {horaBogota(estado.ultima_ejecucion.inicio)} (hora de Bogotá)</Text></>
            : <Text style={s.cuerpo}>Aún no hay revisiones registradas.</Text>}
        </Tarjeta>
      </>}
      {pestana === 'ajustes' && <Ajustes biometria={biometria} version={version} onBiometria={onBiometria} onSalir={onSalir} token={token} onError={setError} />}
    </ScrollView>
    <BarraInferior activa={pestana} onElegir={setPestana} />
  </View>;
}

function Cifra({ icono, valor, texto }: { icono: keyof typeof Ionicons.glyphMap; valor?: number; texto: string }) {
  return <View style={s.cifra}>
    <Ionicons name={icono} size={22} color={colores.marino} />
    <Text style={s.cifraNum}>{valor ?? '–'}</Text>
    <Text style={s.cifraTxt}>{texto}</Text>
  </View>;
}

function Ajustes({ biometria, version, onBiometria, onSalir, token, onError }: Pick<Props, 'biometria' | 'version' | 'onBiometria' | 'onSalir'> & { token: string; onError: (m: string) => void }) {
  const [hayBiometria, setHayBiometria] = useState(false);
  useEffect(() => { void biometriaDisponible().then(setHayBiometria); }, []);

  function confirmarOlvidar() {
    Alert.alert('Olvidar mis credenciales', 'Se borran del servidor tus datos de acceso a SIGAC y Tinotify deja de revisar tu cuenta.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Olvidar', style: 'destructive', onPress: () => {
        olvidarCredenciales(token).then(onSalir, err => onError(err instanceof ErrorApi ? err.message : 'No se completó la operación.'));
      } },
    ]);
  }

  return <>
    <Titulo texto="Ajustes" />
    <Tarjeta>
      <View style={s.ajuste}>
        <View style={{ flex: 1 }}>
          <Text style={s.fuerte}>Desbloqueo con huella o rostro</Text>
          <Text style={s.cuerpo}>{hayBiometria ? 'Pide tu huella o rostro al abrir la app.' : 'Configura una huella o rostro en tu teléfono para activarlo.'}</Text>
        </View>
        <Switch value={biometria} disabled={!hayBiometria} onValueChange={v => { void onBiometria(v); }} accessibilityLabel="Desbloqueo con huella o rostro" trackColor={{ true: colores.marino }} thumbColor={colores.blanco} />
      </View>
    </Tarjeta>
    <Boton texto="Olvidar mis credenciales" secundario icono="trash-outline" onPress={confirmarOlvidar} />
    <View style={{ height: espacio.m }} />
    <Boton texto="Cerrar sesión en este teléfono" secundario icono="log-out-outline" onPress={() => { void onSalir(); }} />
    <Text style={s.version}>Tinotify {version}</Text>
  </>;
}

const s = StyleSheet.create({
  pagina: { padding: 20, paddingTop: 56, paddingBottom: 16 },
  ojos: { position: 'absolute', right: -30, top: -20, width: 150, height: 150, opacity: 0.95 },
  huellas: { position: 'absolute', right: 12, top: 40, width: 110, height: 80, opacity: 0.6 },
  claro: { color: colores.fondo, fontSize: 15, marginTop: 4 }, grande: { color: colores.blanco, fontSize: 24, fontWeight: '700', marginVertical: 6 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  cifras: { flexDirection: 'row', justifyContent: 'space-around' }, cifra: { alignItems: 'center', gap: 2, flex: 1 },
  cifraNum: { fontSize: 26, fontWeight: '700', color: colores.texto }, cifraTxt: { fontSize: 13, color: colores.textoSuave },
  cuerpo: { fontSize: 15, color: colores.textoSuave, lineHeight: 22 }, fuerte: { fontSize: 17, fontWeight: '700', color: colores.texto, marginBottom: 2 },
  ajuste: { flexDirection: 'row', alignItems: 'center', gap: 12 }, version: { textAlign: 'center', color: colores.textoSuave, marginTop: 24, fontSize: 13 },
});
