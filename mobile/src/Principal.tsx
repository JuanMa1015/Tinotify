import { useCallback, useEffect, useState } from 'react';
import { Alert, BackHandler, Image, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import Acceso from './Acceso';
import Ajustes, { type SeccionAjustes } from './Ajustes';
import { CambiarClave, EliminarCuenta } from './AuthPantallas';
import { URL_SIGAC, esTokenDeUsuario } from './cuentas';
import { Aviso, BarraInferior, Boton, Etiqueta, Tarjeta, TarjetaEsqueleto, Titulo, type Icono } from './componentes';
import { ErrorApi, descargarAnexo, marcarVistos, obtenerActuaciones, obtenerEjecuciones, obtenerEstado, obtenerExpedientes, type Actuacion, type Expediente } from './api';
import { type Destino } from './notificaciones';
import {
  canalesDeAviso, duracionTexto, fechaHoraBogota, parsearDescripcion, tipoDireccion, tonoDeEstado, proximaRevision, resumenDeEjecucion, resumenDeEstado, type Ejecucion, type EstadoMonitor,
} from './revisiones';
import { colores, espacio, radios } from './tema';

type Props = {
  token: string; biometria: boolean; version: string;
  onBiometria: (activa: boolean) => Promise<void>; onSalir: () => Promise<void>;
  destino?: Destino | null; onDestinoAtendido?: () => void; correo?: string;
};

const saludo = () => {
  const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'America/Bogota', hour: '2-digit', hour12: false }).format(new Date()));
  return h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
};
const mensajeDe = (err: unknown, otro = 'No se completó la operación.') => (err instanceof ErrorApi ? err.message : otro);

export default function Principal({ token, correo, biometria, version, onBiometria, onSalir, destino, onDestinoAtendido }: Props) {
  const [pestana, setPestana] = useState('inicio');
  const [estado, setEstado] = useState<EstadoMonitor>();
  const [ejecuciones, setEjecuciones] = useState<Ejecucion[]>();
  const [expedientes, setExpedientes] = useState<Expediente[] | null>();  // null: el servidor aún no ofrece el listado
  const [error, setError] = useState('');
  const [refrescando, setRefrescando] = useState(false);
  const [reconectando, setReconectando] = useState(false);
  const [abierto, setAbierto] = useState<Expediente | null>(null);
  const [cuenta, setCuenta] = useState<'cambiar' | 'eliminar' | null>(null);
  const [seccionAjustes, setSeccionAjustes] = useState<SeccionAjustes | null>(null);
  const usuario = esTokenDeUsuario(token);

  const [pendiente, setPendiente] = useState<string | null>(null);  // expediente que pidió abrir una notificación
  useEffect(() => {
    if (!destino) return;
    setPestana(destino.pestana); setAbierto(null); setSeccionAjustes(null);
    if (destino.expediente) setPendiente(destino.expediente);
    onDestinoAtendido?.(); void cargar();
  }, [destino]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // abre el expediente de la notificación en cuanto el listado esté cargado
    if (pendiente && expedientes) { const x = expedientes.find(e => e.id === pendiente); if (x) setAbierto(x); setPendiente(null); }
  }, [pendiente, expedientes]);

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

  useEffect(() => {  // el botón «atrás» de Android sube un nivel; solo cierra la app desde Inicio
    const escucha = BackHandler.addEventListener('hardwareBackPress', () => {
      if (reconectando) { setReconectando(false); return true; }
      if (cuenta) { setCuenta(null); return true; }
      if (abierto) { setAbierto(null); return true; }
      if (pestana === 'ajustes' && seccionAjustes) { setSeccionAjustes(null); return true; }
      if (pestana !== 'inicio') { setPestana('inicio'); return true; }
      return false;
    });
    return () => escucha.remove();
  }, [reconectando, cuenta, abierto, pestana, seccionAjustes]);

  if (reconectando) {
    return <Acceso tokenFijo={token} onCancelar={() => setReconectando(false)} onListo={async () => { setReconectando(false); await cargar(); }} />;
  }

  if (cuenta === 'cambiar') return <CambiarClave token={token} onCancelar={() => setCuenta(null)} onListo={() => { setCuenta(null); Alert.alert('Contraseña actualizada', 'Se cerró la sesión en tus otros dispositivos.'); }} />;
  if (cuenta === 'eliminar') return <EliminarCuenta token={token} onCancelar={() => setCuenta(null)} onEliminada={onSalir} />;
  if (abierto) return <DetalleExpediente token={token} expediente={abierto} onVolver={() => setAbierto(null)} />;

  return <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} refreshControl={<RefreshControl refreshing={refrescando} onRefresh={() => { void cargar(); }} tintColor={colores.marino} />}>
      <Image source={require('../assets/huellas.png')} accessible={false} resizeMode="contain" style={s.huellas} />
      {error !== '' && <Aviso texto={error} />}
      {pestana === 'inicio' && <Inicio estado={estado} onConectar={() => setReconectando(true)} />}
      {pestana === 'casos' && <Casos estado={estado} expedientes={expedientes} token={token} onCambio={setExpedientes} onError={setError} onAbrir={setAbierto} />}
      {pestana === 'actividad' && <Actividad ejecuciones={ejecuciones} />}
      {pestana === 'ajustes' && <Ajustes token={token} usuario={usuario} correo={correo} estado={estado} biometria={biometria} version={version}
        onBiometria={onBiometria} onSalir={onSalir} onReconectar={() => setReconectando(true)} onCuenta={setCuenta}
        seccion={seccionAjustes} onSeccion={setSeccionAjustes} />}
    </ScrollView>
    <BarraInferior activa={pestana} onElegir={setPestana} />
  </View>;
}

function Inicio({ estado, onConectar }: { estado?: EstadoMonitor; onConectar: () => void }) {
  const resumen = estado ? resumenDeEstado(estado) : undefined;
  const proxima = proximaRevision(new Date());
  return <>
    <Titulo texto={saludo()} subtitulo="Resumen del seguimiento de tu cuenta de SIGAC" />
    {!estado ? <><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto /></> : <>
      {!estado.credenciales_guardadas && <Tarjeta>
        <Text style={s.fuerte}>Conecta tu cuenta de SIGAC</Text>
        <Text style={[s.cuerpo, { marginBottom: 10 }]}>Aún no hay credenciales guardadas, así que no se revisa nada. Conéctala para empezar el seguimiento.</Text>
        <Boton texto="Conectar SIGAC" icono="link-outline" onPress={onConectar} />
      </Tarjeta>}
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
      {sinVer > 0 && <View style={s.barraVistos}>
        <Text style={[s.cuerpo, { flex: 1 }]}>{sinVer === 1 ? '1 expediente con novedades sin ver' : `${sinVer} expedientes con novedades sin ver`}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Marcar todo como visto" onPress={() => { void verTodos(); }} style={s.botonVistos}>
          <Ionicons name="checkmark-done" size={18} color={colores.marino} />
          <Text style={s.botonVistosTxt}>Marcar vistos</Text>
        </Pressable>
      </View>}
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

function EstadoExpediente({ estado }: { estado: string }) {
  const tono = tonoDeEstado(estado);
  const c = tono === 'proceso' ? { fondo: '#FFF1D6', texto: '#7A4F00', punto: '#E39B00' }
    : tono === 'cerrado' ? { fondo: '#E7EAF0', texto: '#3D4A60', punto: '#8A97AB' } : { fondo: colores.azulChip, texto: colores.marino, punto: colores.marinoSuave };
  return <View accessibilityLabel={`Estado: ${estado}`} style={[s.estadoChip, { backgroundColor: c.fondo }]}>
    <View style={[s.punto, { backgroundColor: c.punto }]} />
    <Text style={[s.estadoTxt, { color: c.texto }]}>{estado}</Text>
  </View>;
}

function Anexo({ anexo, token, expediente, actuacion, indice }: { anexo: Actuacion['anexos'][number]; token: string; expediente: string; actuacion: number; indice: number }) {
  const disponible = anexo.con_enlace === true;
  const [bajando, setBajando] = useState(false);
  const [error, setError] = useState('');

  async function bajar() {
    setBajando(true); setError('');
    try { await descargarAnexo(token, expediente, actuacion, indice, anexo.archivo || anexo.descripcion || 'anexo'); }
    catch (err) { setError(mensajeDe(err, 'No se pudo descargar el anexo.')); }
    finally { setBajando(false); }
  }

  return <View style={[s.anexo, disponible ? s.anexoActivo : s.anexoInactivo, { flexDirection: 'column', alignItems: 'stretch' }]}>
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
      <Ionicons name={disponible ? 'document-attach' : 'document-outline'} size={22} color={disponible ? colores.marino : colores.textoSuave} />
      <View style={{ flex: 1 }}>
        <Text style={s.fuerteChico}>{anexo.descripcion || 'Anexo'}</Text>
        {anexo.archivo !== '' && <Text style={s.pequeno}>{anexo.archivo}</Text>}
        <Text style={[s.pequeno, { color: disponible ? '#3F7D1A' : colores.textoSuave, fontWeight: '600' }]}>
          {disponible ? 'Archivo disponible' : 'Sin archivo descargable'}</Text>
      </View>
      {disponible && <Pressable accessibilityRole="button" accessibilityLabel={`Descargar ${anexo.archivo || anexo.descripcion}`} disabled={bajando} onPress={() => { void bajar(); }}
        style={[s.abrirSigac, bajando && { opacity: 0.6 }]}>
        <Text style={s.abrirSigacTxt}>{bajando ? 'Descargando…' : 'Descargar'}</Text></Pressable>}
    </View>
    {error !== '' && <>
      <Text style={[s.pequeno, { color: colores.error }]} accessibilityLiveRegion="polite">{error}</Text>
      <Text style={s.enlace} accessibilityRole="link" onPress={() => { void Linking.openURL(URL_SIGAC); }}>Abrir SIGAC</Text>
    </>}
  </View>;
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
      <View style={s.cabecera}>
        <Text style={s.radicado}>RADICADO {expediente.numero}</Text>
        <Text accessibilityRole="header" style={s.clienteGrande}>{expediente.cliente}</Text>
        <View style={s.chips}>
          <EstadoExpediente estado={expediente.estado} />
          {actuaciones && <View accessibilityLabel={`${actuaciones.length} actuaciones`} style={s.cuenta}>
            <Ionicons name="documents-outline" size={16} color={colores.marino} />
            <Text style={s.cuentaTxt}>{actuaciones.length} {actuaciones.length === 1 ? 'actuación' : 'actuaciones'}</Text>
          </View>}
        </View>
      </View>
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
          {a.anexos.length > 0 && <View style={{ marginTop: 10, gap: 8 }}>
            <Text style={s.pequeno}>Anexos ({a.anexos.length})</Text>
            {a.anexos.map((x, j) => <Anexo key={j} anexo={x} token={token} expediente={expediente.id} actuacion={i} indice={j} />)}
          </View>}
        </Tarjeta>))}
      <Text style={s.pequeno}>Lectura en vivo desde SIGAC a través de tu cuenta. Tinotify no guarda el contenido de las actuaciones.</Text>
    </ScrollView>
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
  cabecera: { marginBottom: espacio.l },
  barraVistos: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colores.azulChip, borderRadius: radios.medio, paddingVertical: 10, paddingLeft: 14, paddingRight: 10, marginTop: 14, marginBottom: 14 },
  botonVistos: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colores.blanco, borderWidth: 1, borderColor: colores.borde, borderRadius: radios.pildora, paddingHorizontal: 12, paddingVertical: 8 },
  botonVistosTxt: { fontSize: 14, fontWeight: '700', color: colores.marino },
  estadoChip: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radios.pildora },
  estadoTxt: { fontSize: 14, fontWeight: '700' }, punto: { width: 9, height: 9, borderRadius: 5 },
  cuenta: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 7, borderRadius: radios.chico, borderWidth: 1, borderColor: colores.borde, backgroundColor: colores.blanco },
  cuentaTxt: { fontSize: 14, fontWeight: '600', color: colores.marino },
  radicado: { fontSize: 13, fontWeight: '700', color: colores.textoSuave, letterSpacing: 0.8 },
  clienteGrande: { fontSize: 26, fontWeight: '700', color: colores.texto, lineHeight: 32, marginTop: 4 },
  fuerteChico: { fontSize: 15, fontWeight: '700', color: colores.texto },
  anexo: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, borderRadius: radios.chico, borderWidth: 1 },
  anexoActivo: { backgroundColor: colores.limaSuave, borderColor: '#9DC356' },
  anexoInactivo: { backgroundColor: colores.superficie, borderColor: colores.borde },
  abrirSigac: { backgroundColor: colores.marino, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radios.pildora },
  abrirSigacTxt: { color: colores.blanco, fontSize: 13, fontWeight: '700' },
  sentido: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, marginVertical: 6 },
  sentidoTxt: { fontSize: 13, fontWeight: '700', color: colores.marino, textTransform: 'uppercase', letterSpacing: 0.4 },
  etiquetaFila: { fontSize: 13, fontWeight: '700', color: colores.marinoSuave, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 2 },
  buscar: { borderWidth: 1, borderColor: colores.borde, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 12, fontSize: 16, color: colores.texto, backgroundColor: colores.superficie, marginBottom: 12 },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: colores.azulChip }, chipOn: { backgroundColor: colores.marino }, chipTxt: { fontSize: 14, fontWeight: '600', color: colores.marino },
  seccion: { fontSize: 14, fontWeight: '700', color: colores.textoSuave, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 20, marginBottom: 8 },
});
