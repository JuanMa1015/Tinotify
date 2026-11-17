import { useCallback, useEffect, useState } from 'react';
import { Alert, Image, Linking, RefreshControl, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import Acceso from './Acceso';
import { Aviso, BarraInferior, Boton, Etiqueta, Tarjeta, TarjetaEsqueleto, Titulo, type Icono } from './componentes';
import { ErrorApi, obtenerEjecuciones, obtenerEstado, olvidarCredenciales } from './api';
import { biometriaDisponible } from './almacen';
import { activarPush, desactivarPush, pushActivo } from './notificaciones';
import {
  duracionTexto, fechaHoraBogota, proximaRevision, resumenDeEjecucion, resumenDeEstado, type Ejecucion, type EstadoMonitor,
} from './revisiones';
import { colores, espacio } from './tema';

type Props = {
  token: string; biometria: boolean; version: string;
  onBiometria: (activa: boolean) => Promise<void>; onSalir: () => Promise<void>;
};

const saludo = () => {
  const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'America/Bogota', hour: '2-digit', hour12: false }).format(new Date()));
  return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
};
const mensajeDe = (err: unknown, otro = 'No se completó la operación.') => (err instanceof ErrorApi ? err.message : otro);

export default function Principal({ token, biometria, version, onBiometria, onSalir }: Props) {
  const [pestana, setPestana] = useState('inicio');
  const [estado, setEstado] = useState<EstadoMonitor>();
  const [ejecuciones, setEjecuciones] = useState<Ejecucion[]>();
  const [error, setError] = useState('');
  const [refrescando, setRefrescando] = useState(false);
  const [reconectando, setReconectando] = useState(false);

  const cargar = useCallback(async () => {
    setRefrescando(true);
    try {
      const [e, x] = await Promise.all([obtenerEstado(token), obtenerEjecuciones(token)]);
      setEstado(e); setEjecuciones(x.ejecuciones); setError('');
    } catch (err) {
      setError(mensajeDe(err, 'No se pudo actualizar.'));
      if (err instanceof ErrorApi && err.estado === 401) await onSalir();
    } finally { setRefrescando(false); }
  }, [token, onSalir]);

  useEffect(() => { void cargar(); }, [cargar]);

  if (reconectando) {
    return <Acceso tokenFijo={token} onCancelar={() => setReconectando(false)} onListo={async () => { setReconectando(false); await cargar(); }} />;
  }

  return <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} refreshControl={<RefreshControl refreshing={refrescando} onRefresh={() => { void cargar(); }} tintColor={colores.marino} />}>
      <Image source={require('../assets/huellas.png')} accessible={false} resizeMode="contain" style={s.huellas} />
      {error !== '' && <Aviso texto={error} />}
      {pestana === 'inicio' && <Inicio estado={estado} />}
      {pestana === 'casos' && <Casos estado={estado} />}
      {pestana === 'actividad' && <Actividad ejecuciones={ejecuciones} />}
      {pestana === 'ajustes' && <Ajustes biometria={biometria} version={version} onBiometria={onBiometria} onSalir={onSalir} token={token}
        onError={setError} onReconectar={() => setReconectando(true)} />}
    </ScrollView>
    <BarraInferior activa={pestana} onElegir={setPestana} />
  </View>;
}

function Inicio({ estado }: { estado?: EstadoMonitor }) {
  const resumen = estado ? resumenDeEstado(estado) : undefined;
  const proxima = proximaRevision(new Date());
  return <>
    <Titulo texto={saludo()} subtitulo="Resumen del seguimiento de tu cuenta de SIGAC" />
    {!estado ? <><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto /></> : <>
      <Tarjeta oscura estilo={{ overflow: 'hidden' }}>
        <Image source={require('../assets/gato-ojos.png')} accessible={false} resizeMode="contain" style={s.ojos} />
        <Text style={s.claro}><Ionicons name="calendar-outline" size={14} /> Última revisión</Text>
        <Text style={s.grande}>{estado.ultima_ejecucion ? fechaHoraBogota(estado.ultima_ejecucion.inicio) : 'Aún sin revisiones'}</Text>
        <Text style={s.mediano}>{resumen?.titulo}</Text>
        <Text style={s.claro}>{resumen?.detalle}</Text>
        <View style={s.chips}>
          <Etiqueta texto={`Próxima ${proxima.etiqueta}`} tono="azul" />
          <Etiqueta texto={resumen?.requiereAtencion ? 'Requiere atención' : 'Sin errores'} tono={resumen?.requiereAtencion ? 'rojo' : 'lima'} />
        </View>
      </Tarjeta>
      <Tarjeta>
        <View style={s.cifras}>
          <Cifra icono="folder-outline" valor={estado.expedientes_en_estado} texto="Expedientes" />
          <Cifra icono="refresh-outline" valor={3} texto="Revisiones al día" />
          <Cifra icono="notifications-outline" valor={estado.avisos_pendientes} texto="Avisos pendientes" />
        </View>
      </Tarjeta>
    </>}
  </>;
}

function Cifra({ icono, valor, texto }: { icono: Icono; valor?: number; texto: string }) {
  return <View style={s.cifra}>
    <Ionicons name={icono} size={22} color={colores.marino} />
    <Text style={s.cifraNum}>{valor ?? '–'}</Text>
    <Text style={s.cifraTxt}>{texto}</Text>
  </View>;
}

function Casos({ estado }: { estado?: EstadoMonitor }) {
  return <>
    <Titulo texto="Expedientes" subtitulo={estado ? `${estado.expedientes_en_estado} en seguimiento` : undefined} />
    {!estado ? <TarjetaEsqueleto lineas={3} /> : <Tarjeta>
      <Text style={s.cuerpo}>Tinotify vigila todos los expedientes de tu cuenta de SIGAC en cada revisión y te avisa de las actuaciones nuevas y de los expedientes que aparezcan.</Text>
      <Text style={[s.cuerpo, { marginTop: 8 }]}>Por privacidad, el servidor no conserva radicados ni el contenido de las actuaciones. El listado con el detalle de cada expediente llegará en una próxima versión.</Text>
    </Tarjeta>}
  </>;
}

function Actividad({ ejecuciones }: { ejecuciones?: Ejecucion[] }) {
  return <>
    <Titulo texto="Actividad" subtitulo="Historial de revisiones de tu cuenta" />
    {!ejecuciones ? <><TarjetaEsqueleto /><TarjetaEsqueleto /><TarjetaEsqueleto /></> :
      ejecuciones.length === 0 ? <Tarjeta><Text style={s.cuerpo}>Aún no hay revisiones registradas. La primera se hará en el próximo horario (7:30, 12:30 o 18:30).</Text></Tarjeta> :
      ejecuciones.map((x, i) => {
        const r = resumenDeEjecucion(x);
        const dur = duracionTexto(x.inicio, x.fin);
        return <Tarjeta key={`${x.inicio}-${i}`}>
          <View style={s.fila}>
            <Ionicons name={r.ok ? 'checkmark-circle' : 'alert-circle'} size={26} color={r.ok ? '#3F7D1A' : colores.error} />
            <View style={{ flex: 1 }}>
              <Text style={s.fuerte}>{r.titulo}</Text>
              <Text style={s.cuerpo}>{r.detalle}</Text>
              <Text style={s.pequeno}>{fechaHoraBogota(x.inicio)}{dur ? ` · duró ${dur}` : ''}</Text>
            </View>
          </View>
        </Tarjeta>;
      })}
    <Text style={s.pequeno}>Se muestran las últimas 30 revisiones. Hora de Bogotá.</Text>
  </>;
}

type AjustesProps = Pick<Props, 'biometria' | 'version' | 'onBiometria' | 'onSalir'> & { token: string; onError: (m: string) => void; onReconectar: () => void };

function Ajustes({ biometria, version, onBiometria, onSalir, token, onError, onReconectar }: AjustesProps) {
  const [hayBiometria, setHayBiometria] = useState(false);
  const [push, setPush] = useState(false);
  useEffect(() => { void biometriaDisponible().then(setHayBiometria); void pushActivo().then(setPush); }, []);

  async function cambiarPush(activar: boolean) {
    try {
      if (activar) {
        if ((await activarPush(token)) === 'permiso_denegado') { onError('Permite las notificaciones en los ajustes de Android.'); return; }
      } else await desactivarPush(token);
      setPush(activar); onError('');
    } catch (err) { onError(mensajeDe(err, 'No se pudieron cambiar las notificaciones.')); }
  }

  function confirmarOlvidar() {
    Alert.alert('Olvidar mis credenciales', 'Se borran del servidor tu usuario y clave de SIGAC y tu estado de seguimiento. Tinotify dejará de revisar tu cuenta hasta que la conectes de nuevo.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Borrar', style: 'destructive', onPress: () => { olvidarCredenciales(token).then(onSalir, err => onError(mensajeDe(err))); } },
    ]);
  }

  return <>
    <Titulo texto="Ajustes" />
    <Seccion texto="Cuenta de SIGAC" />
    <Boton texto="Actualizar mi clave de SIGAC" secundario icono="key-outline" onPress={onReconectar} />
    <Texto>Úsalo si cambiaste tu clave en SIGAC. Mientras no la actualices, las revisiones fallarán.</Texto>
    <Boton texto="Olvidar mis credenciales" secundario icono="trash-outline" onPress={confirmarOlvidar} />
    <Texto>Borra del servidor tus datos de acceso y el estado de seguimiento.</Texto>

    <Seccion texto="Avisos" />
    <Tarjeta>
      <Fila titulo="Notificaciones en este teléfono" detalle="Un aviso cuando haya actuaciones nuevas o aparezca un expediente nuevo." valor={push} onCambio={cambiarPush} />
    </Tarjeta>

    <Seccion texto="Seguridad" />
    <Tarjeta>
      <Fila titulo="Desbloqueo con huella o rostro" detalle={hayBiometria ? 'Se pide al abrir la aplicación.' : 'Configura una huella o un rostro en el teléfono para activarlo.'}
        valor={biometria} desactivado={!hayBiometria} onCambio={onBiometria} />
    </Tarjeta>
    <Boton texto="Cerrar sesión en este teléfono" secundario icono="log-out-outline" onPress={() => { void onSalir(); }} />

    <Seccion texto="Privacidad" />
    <Tarjeta>
      <Text style={s.cuerpo}>Tu usuario y clave de SIGAC se guardan cifrados en el servidor y nunca en este teléfono. No se conserva el contenido de tus expedientes: solo resúmenes cifrados para detectar cambios y conteos. Los avisos no incluyen datos de los casos.</Text>
      <Text style={s.enlace} accessibilityRole="link" onPress={() => { void Linking.openURL('https://github.com/JuanMa1015/Tinotify/blob/main/docs/legal/politica-tratamiento-datos.md'); }}>Política de tratamiento de datos</Text>
    </Tarjeta>

    <Seccion texto="Acerca de" />
    <Tarjeta>
      <Text style={s.fuerte}>Tinotify {version}</Text>
      <Text style={s.cuerpo}>Tinotify no está afiliado a SIGAC. Los avisos son una ayuda: confirma siempre la información en el sistema oficial.</Text>
    </Tarjeta>
  </>;
}

const Seccion = ({ texto }: { texto: string }) => <Text accessibilityRole="header" style={s.seccion}>{texto}</Text>;
const Texto = ({ children }: { children: string }) => <Text style={[s.pequeno, { marginBottom: espacio.m }]}>{children}</Text>;

function Fila({ titulo, detalle, valor, onCambio, desactivado }: { titulo: string; detalle: string; valor: boolean; onCambio: (v: boolean) => Promise<void> | void; desactivado?: boolean }) {
  return <View style={s.fila}>
    <View style={{ flex: 1 }}>
      <Text style={s.fuerte}>{titulo}</Text>
      <Text style={s.cuerpo}>{detalle}</Text>
    </View>
    <Switch value={valor} disabled={desactivado} onValueChange={v => { void onCambio(v); }} accessibilityLabel={titulo} trackColor={{ true: colores.marino }} thumbColor={colores.blanco} />
  </View>;
}

const s = StyleSheet.create({
  pagina: { padding: 20, paddingTop: 56, paddingBottom: 16 },
  huellas: { position: 'absolute', right: 12, top: 40, width: 110, height: 80, opacity: 0.6 },
  ojos: { position: 'absolute', right: -30, top: -20, width: 150, height: 150, opacity: 0.95 },
  claro: { color: colores.fondo, fontSize: 15, marginTop: 4 },
  grande: { color: colores.blanco, fontSize: 26, fontWeight: '700', marginVertical: 4 },
  mediano: { color: colores.lima, fontSize: 18, fontWeight: '600', marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  cifras: { flexDirection: 'row', justifyContent: 'space-around' }, cifra: { alignItems: 'center', gap: 2, flex: 1 },
  cifraNum: { fontSize: 26, fontWeight: '700', color: colores.texto }, cifraTxt: { fontSize: 13, color: colores.textoSuave, textAlign: 'center' },
  cuerpo: { fontSize: 15, color: colores.textoSuave, lineHeight: 22 }, fuerte: { fontSize: 17, fontWeight: '700', color: colores.texto, marginBottom: 2 },
  pequeno: { fontSize: 13, color: colores.textoSuave, marginTop: 4 }, enlace: { fontSize: 15, color: colores.marinoSuave, fontWeight: '600', marginTop: 10, textDecorationLine: 'underline' },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  seccion: { fontSize: 14, fontWeight: '700', color: colores.textoSuave, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 20, marginBottom: 8 },
});
