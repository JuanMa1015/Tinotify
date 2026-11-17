import { useCallback, useEffect, useState } from 'react';
import { Alert, Image, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import Acceso from './Acceso';
import { Aviso, BarraInferior, Boton, Etiqueta, Tarjeta, TarjetaEsqueleto, Titulo, type Icono } from './componentes';
import { ErrorApi, enviarPrueba, marcarVistos, obtenerActuaciones, obtenerEjecuciones, obtenerEstado, obtenerExpedientes, olvidarCredenciales, type Actuacion, type Expediente } from './api';
import { biometriaDisponible } from './almacen';
import { activarPush, desactivarPush, pushActivo, type Pestana } from './notificaciones';
import {
  canalesDeAviso, duracionTexto, fechaHoraBogota, parsearDescripcion, tipoDireccion, proximaRevision, resumenDeEjecucion, resumenDeEstado, type Ejecucion, type EstadoMonitor,
} from './revisiones';
import { colores, espacio } from './tema';

type Props = {
  token: string; biometria: boolean; version: string;
  onBiometria: (activa: boolean) => Promise<void>; onSalir: () => Promise<void>;
  destino?: Pestana | null; onDestinoAtendido?: () => void;
};

const saludo = () => {
  const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'America/Bogota', hour: '2-digit', hour12: false }).format(new Date()));
  return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
};
const mensajeDe = (err: unknown, otro = 'No se completó la operación.') => (err instanceof ErrorApi ? err.message : otro);

export default function Principal({ token, biometria, version, onBiometria, onSalir, destino, onDestinoAtendido }: Props) {
  const [pestana, setPestana] = useState('inicio');
  const [estado, setEstado] = useState<EstadoMonitor>();
  const [ejecuciones, setEjecuciones] = useState<Ejecucion[]>();
  const [expedientes, setExpedientes] = useState<Expediente[] | null>();  // null: el servidor aún no ofrece el listado
  const [error, setError] = useState('');
  const [refrescando, setRefrescando] = useState(false);
  const [reconectando, setReconectando] = useState(false);
  const [abierto, setAbierto] = useState<Expediente | null>(null);

  useEffect(() => { if (destino) { setPestana(destino); onDestinoAtendido?.(); void cargar(); } }, [destino]);  // eslint-disable-line react-hooks/exhaustive-deps

  const cargar = useCallback(async () => {
    setRefrescando(true);
    try {
      obtenerExpedientes(token).then(r => setExpedientes(r.expedientes), () => setExpedientes(prev => prev ?? null));
      const [e, x] = await Promise.all([obtenerEstado(token), obtenerEjecuciones(token).catch(() => ({ ejecuciones: [] as Ejecucion[] }))]);  // el historial es secundario: si falla, el resto sigue
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

  if (abierto) return <DetalleExpediente token={token} expediente={abierto} onVolver={() => setAbierto(null)} />;

  return <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} refreshControl={<RefreshControl refreshing={refrescando} onRefresh={() => { void cargar(); }} tintColor={colores.marino} />}>
      <Image source={require('../assets/huellas.png')} accessible={false} resizeMode="contain" style={s.huellas} />
      {error !== '' && <Aviso texto={error} />}
      {pestana === 'inicio' && <Inicio estado={estado} />}
      {pestana === 'casos' && <Casos estado={estado} expedientes={expedientes} token={token} onCambio={setExpedientes} onError={setError} onAbrir={setAbierto} />}
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

function Casos({ estado, expedientes, token, onCambio, onError, onAbrir }: { estado?: EstadoMonitor; expedientes?: Expediente[] | null; token: string; onCambio: (e: Expediente[]) => void; onError: (m: string) => void; onAbrir: (x: Expediente) => void }) {
  const [filtro, setFiltro] = useState<'todos' | 'novedades' | 'nuevos'>('todos');
  const [busqueda, setBusqueda] = useState('');
  const lista = expedientes ?? [];
  const q = busqueda.trim().toLowerCase();
  const visibles = lista.filter(x => (filtro === 'todos' || (filtro === 'novedades' ? x.novedades_no_vistas > 0 : x.nuevo))
    && (q === '' || String(x.numero).includes(q) || x.cliente.toLowerCase().includes(q)));
  const sinVer = lista.filter(x => x.novedades_no_vistas > 0 || x.nuevo).length;

  async function ver(x: Expediente) {
    onAbrir(x);
    if (!x.novedades_no_vistas && !x.nuevo) return;
    onCambio(lista.map(y => (y.id === x.id ? { ...y, novedades_no_vistas: 0, nuevo: false } : y)));  // se ve al instante
    try { await marcarVistos(token, x.id); } catch (err) { onError(mensajeDe(err)); }
  }
  async function verTodos() {
    onCambio(lista.map(y => ({ ...y, novedades_no_vistas: 0, nuevo: false })));
    try { await marcarVistos(token); } catch (err) { onError(mensajeDe(err)); }
  }

  return <>
    <Titulo texto="Expedientes" subtitulo={estado ? `${estado.expedientes_en_estado} en seguimiento` : undefined} />
    {expedientes === undefined ? <><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto lineas={3} /></> :
      expedientes === null ? <Tarjeta><Text style={s.cuerpo}>El listado de expedientes aún no está disponible en el servidor. Tinotify sigue vigilando tu cuenta y te avisará de las novedades.</Text></Tarjeta> : <>
      <TextInput accessibilityLabel="Buscar por radicado o nombre" placeholder="Buscar por radicado o nombre" placeholderTextColor={colores.textoSuave}
        value={busqueda} onChangeText={setBusqueda} autoCorrect={false} style={s.buscar} />
      <View style={s.chips}>
        {([['todos', 'Todos'], ['novedades', 'Con novedades'], ['nuevos', 'Nuevos']] as const).map(([id, texto]) =>
          <Pressable key={id} accessibilityRole="button" accessibilityState={{ selected: filtro === id }} onPress={() => setFiltro(id)}
            style={[s.chip, filtro === id && s.chipOn]}><Text style={[s.chipTxt, filtro === id && { color: colores.blanco }]}>{texto}</Text></Pressable>)}
      </View>
      {sinVer > 0 && <Text style={s.enlace} accessibilityRole="button" onPress={() => { void verTodos(); }}>Marcar todo como visto ({sinVer})</Text>}
      {visibles.length === 0 ? <Tarjeta><Text style={s.cuerpo}>{lista.length === 0 ? 'Aún no hay expedientes guardados. Aparecerán tras la próxima revisión.' : 'Ningún expediente coincide con el filtro.'}</Text></Tarjeta> :
        visibles.map(x => <Pressable key={x.id} accessibilityRole="button" onPress={() => { void ver(x); }}>
          <Tarjeta>
            <View style={s.fila}>
              <View style={{ flex: 1 }}>
                <Text style={s.fuerte}>Radicado {x.numero}</Text>
                <Text style={s.cuerpo}>{x.cliente}</Text>
                <Text style={s.pequeno}>{x.estado}{x.ultima_novedad ? ` · última novedad ${fechaHoraBogota(x.ultima_novedad)}` : ''}</Text>
              </View>
              {x.novedades_no_vistas > 0 ? <Etiqueta texto={`${x.novedades_no_vistas} ${x.novedades_no_vistas === 1 ? 'nueva' : 'nuevas'}`} tono="azul" /> :
                x.nuevo ? <Etiqueta texto="Nuevo" tono="lima" /> : null}
            </View>
          </Tarjeta>
        </Pressable>)}
    </>}
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
              {canalesDeAviso(x.aviso).map(c => <Text key={c.texto} style={[s.pequeno, { color: c.ok ? '#3F7D1A' : colores.error, fontWeight: '600' }]}>{c.ok ? '✓' : '✕'} {c.texto}</Text>)}
            </View>
          </View>
        </Tarjeta>;
      })}
    <Text style={s.pequeno}>Se muestran las últimas 30 revisiones. Hora de Bogotá.</Text>
  </>;
}

function Sentido({ origen, destino }: { origen: string; destino: string }) {
  const tipo = tipoDireccion(origen, destino);
  const fondo = tipo === 'estudiante_asesor' ? colores.azulChip : tipo === 'asesor_estudiante' ? colores.limaSuave : colores.superficie;
  const borde = tipo === 'estudiante_asesor' ? colores.marinoSuave : tipo === 'asesor_estudiante' ? '#7FA82B' : colores.borde;
  return <View accessibilityLabel={`De ${origen} a ${destino}`} style={[s.sentido, { backgroundColor: fondo, borderColor: borde }]}>
    <Text style={s.sentidoTxt}>{origen}</Text>
    <Ionicons name="arrow-forward" size={16} color={colores.marino} />
    <Text style={s.sentidoTxt}>{destino}</Text>
  </View>;
}

function Descripcion({ texto }: { texto: string }) {
  const d = parsearDescripcion(texto);
  if (d.tipo === 'texto') return <Text style={[s.cuerpo, { marginTop: 6 }]}>{d.texto}</Text>;
  return <View style={{ marginTop: 8, gap: 10 }}>
    {d.filas.map((f, i) => <View key={i}>
      <Text style={s.etiquetaFila}>{f.etiqueta}</Text>
      <Text style={s.cuerpo}>{f.valor}</Text>
    </View>)}
  </View>;
}

function DetalleExpediente({ token, expediente, onVolver }: { token: string; expediente: Expediente; onVolver: () => void }) {
  const [actuaciones, setActuaciones] = useState<Actuacion[]>();
  const [error, setError] = useState('');
  const [intento, setIntento] = useState(0);
  useEffect(() => {
    let vivo = true;
    setActuaciones(undefined); setError('');
    obtenerActuaciones(token, expediente.id).then(r => { if (vivo) setActuaciones(r.actuaciones); },
      err => { if (vivo) setError(mensajeDe(err, 'No se pudo leer el expediente.')); });
    return () => { vivo = false; };
  }, [token, expediente.id, intento]);

  return <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina}>
      <Pressable accessibilityRole="button" accessibilityLabel="Volver a expedientes" onPress={onVolver} style={s.volver}>
        <Ionicons name="chevron-back" size={22} color={colores.marino} /><Text style={s.fuerte}>Expedientes</Text>
      </Pressable>
      <Titulo texto={`Radicado ${expediente.numero}`} subtitulo={`${expediente.cliente} · ${expediente.estado}`} />
      {error !== '' && <><Aviso texto={error} /><Boton texto="Reintentar" secundario icono="refresh-outline" onPress={() => setIntento(n => n + 1)} /></>}
      {error === '' && actuaciones === undefined && <>
        <Text style={s.pequeno}>Leyendo SIGAC… puede tardar hasta un minuto.</Text>
        <TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto lineas={3} />
      </>}
      {actuaciones && (actuaciones.length === 0 ? <Tarjeta><Text style={s.cuerpo}>Este expediente no tiene actuaciones en SIGAC.</Text></Tarjeta> :
        actuaciones.map((a, i) => <Tarjeta key={`${a.fecha}-${i}`}>
          <Text style={s.pequeno}>{fechaHoraBogota(a.fecha)}</Text>
          <Text style={s.fuerte}>{a.etapa || 'Actuación'}</Text>
          {(a.origen || a.destino) && <Sentido origen={a.origen} destino={a.destino} />}
          {a.remitente !== '' && <Text style={s.pequeno}>Remitente: {a.remitente}</Text>}
          <Descripcion texto={a.descripcion} />
          {a.anexos.length > 0 && <View style={{ marginTop: 8 }}>
            <Text style={s.pequeno}>Anexos ({a.anexos.length})</Text>
            {a.anexos.map((x, j) => <Text key={j} style={s.cuerpo}>• {x.descripcion}{x.archivo ? ` — ${x.archivo}` : x.sin_enlace ? ' (sin archivo descargable)' : ''}</Text>)}
          </View>}
        </Tarjeta>))}
      <Text style={s.pequeno}>Lectura en vivo desde SIGAC a través de tu cuenta. Tinotify no guarda el contenido de las actuaciones.</Text>
    </ScrollView>
  </View>;
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

  async function probarPush() {
    try {
      const r = await enviarPrueba(token);
      onError(r.enviados > 0 ? '' : 'No hay ningún teléfono registrado. Activa las notificaciones e inténtalo de nuevo.');
      if (r.enviados > 0) Alert.alert('Notificación enviada', 'Debería llegar en unos segundos. Tócala para comprobar que abre la aplicación.');
    } catch (err) { onError(mensajeDe(err, 'No se pudo enviar la notificación de prueba.')); }
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

    <Boton texto="Enviar notificación de prueba" secundario icono="paper-plane-outline" onPress={() => { void probarPush(); }} />
    <Texto>Comprueba que este teléfono recibe los avisos. No modifica tus expedientes.</Texto>

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
  volver: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 12 },
  sentido: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, marginVertical: 6 },
  sentidoTxt: { fontSize: 13, fontWeight: '700', color: colores.marino, textTransform: 'uppercase', letterSpacing: 0.4 },
  etiquetaFila: { fontSize: 13, fontWeight: '700', color: colores.marinoSuave, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 2 },
  buscar: { borderWidth: 1, borderColor: colores.borde, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 12, fontSize: 16, color: colores.texto, backgroundColor: colores.superficie, marginBottom: 12 },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: colores.azulChip }, chipOn: { backgroundColor: colores.marino }, chipTxt: { fontSize: 14, fontWeight: '600', color: colores.marino },
  seccion: { fontSize: 14, fontWeight: '700', color: colores.textoSuave, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 20, marginBottom: 8 },
});
