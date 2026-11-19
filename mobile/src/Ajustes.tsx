import { useEffect, useState } from 'react';
import { Alert, Linking, Pressable, Share, StyleSheet, Switch, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Aviso, Boton, Campo, Etiqueta, Tarjeta, Titulo, type Icono } from './componentes';
import { ErrorApi, crearInvitacion, enviarPrueba, olvidarCredenciales, probarCorreo } from './api';
import { biometriaDisponible } from './almacen';
import { URL_POLITICA, URL_TERMINOS } from './cuentas';
import { activarPush, desactivarPush, pushActivo } from './notificaciones';
import { primerNombre, type EstadoMonitor } from './revisiones';
import { colores, espacio, radios } from './tema';

export type SeccionAjustes = 'cuenta' | 'sigac' | 'avisos' | 'seguridad' | 'privacidad' | 'acerca';

type Props = {
  token: string; usuario: boolean; admin: boolean; correo?: string; nombre: string; nombreSigac: string; onNombre: (n: string) => void; estado?: EstadoMonitor; biometria: boolean; version: string;
  onBiometria: (activa: boolean) => Promise<void>; onSalir: () => Promise<void>;
  onReconectar: () => void; onCuenta: (c: 'eliminar') => void;
  seccion: SeccionAjustes | null; onSeccion: (s: SeccionAjustes | null) => void;
};

const mensajeDe = (err: unknown, otro = 'No se completó la operación.') => (err instanceof ErrorApi ? err.message : otro);

export default function Ajustes(p: Props) {
  const [error, setError] = useState('');
  const [push, setPush] = useState(false);
  const [hayBiometria, setHayBiometria] = useState(false);
  const [borrador, setBorrador] = useState(p.nombre);
  const [cambiando, setCambiando] = useState(false);
  useEffect(() => { void biometriaDisponible().then(setHayBiometria); void pushActivo().then(setPush); }, []);

  async function cambiarPush(activar: boolean) {
    try {
      if (activar) {
        if ((await activarPush(p.token)) === 'permiso_denegado') { setError('Permite las notificaciones en los ajustes de Android.'); return; }
      } else await desactivarPush(p.token);
      setPush(activar); setError('');
    } catch (err) { setError(mensajeDe(err, 'No se pudieron cambiar las notificaciones.')); }
  }

  async function probarPush() {
    try {
      const r = await enviarPrueba(p.token);
      if (r.enviados > 0) { setError(''); Alert.alert('Notificación enviada', 'Debería llegar en unos segundos. Tócala para comprobar que abre la aplicación.'); }
      else setError('No hay ningún teléfono registrado. Activa las notificaciones e inténtalo de nuevo.');
    } catch (err) { setError(mensajeDe(err, 'No se pudo enviar la notificación de prueba.')); }
  }

  async function probarElCorreo() {
    try {
      const r = await probarCorreo(p.token);
      if (r.enviado) { setError(''); Alert.alert('Correo enviado', 'Revisa la bandeja (y el spam) del correo remitente configurado en Brevo.'); }
      else setError(`No se pudo enviar el correo de prueba: ${r.motivo ?? 'motivo desconocido'}`);
    } catch (err) { setError(mensajeDe(err, 'No se pudo enviar el correo de prueba.')); }
  }

  async function invitar() {
    try {
      const r = await crearInvitacion(p.token);
      await Share.share({ message: `Código de invitación de Tinotify (vale ${r.vigencia_dias} días y un solo uso): ${r.codigo}` });
    } catch (err) { setError(mensajeDe(err, 'No se pudo crear la invitación.')); }
  }

  function confirmarOlvidar() {
    Alert.alert('Desconectar mi cuenta de SIGAC', 'Se borran tu usuario y clave de SIGAC y tu estado de seguimiento. Tinotify dejará de revisar tu cuenta hasta que la conectes de nuevo.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Borrar', style: 'destructive', onPress: () => { olvidarCredenciales(p.token).then(p.onSalir, err => setError(mensajeDe(err))); } },
    ]);
  }

  const conectada = p.estado?.credenciales_guardadas;

  // ---- Menú principal ---------------------------------------------------------------------------------------------
  if (p.seccion === null) {
    return <>
      <Titulo texto="Ajustes" />
      <Tarjeta>
        <View style={s.perfil}>
          <View style={s.avatar}><Ionicons name="person" size={26} color={colores.lima} /></View>
          <View style={{ flex: 1 }}>
            <Text style={s.perfilNombre} numberOfLines={1}>{p.usuario ? (p.correo ?? 'Mi cuenta') : 'Propietario'}</Text>
            <Text style={s.cuerpo}>{p.usuario ? 'Cuenta de Tinotify' : 'Acceso del propietario'}</Text>
          </View>
        </View>
      </Tarjeta>
      {error !== '' && <Aviso texto={error} />}
      <Tarjeta estilo={{ padding: 0, overflow: 'hidden' }}>
        <FilaNav icono="person-outline" titulo="Mi cuenta" detalle={p.usuario ? 'Contraseña y sesión' : 'Invitaciones y sesión'} onPress={() => p.onSeccion('cuenta')} />
        {!p.admin && <FilaNav icono="link-outline" titulo="Conexión con SIGAC" detalle={conectada === undefined ? 'Cargando…' : conectada ? 'Conectada' : 'Sin conectar'} alerta={conectada === false} onPress={() => p.onSeccion('sigac')} />}
        {!p.admin && <FilaNav icono="notifications-outline" titulo="Notificaciones" detalle={push ? 'Activadas en este teléfono' : 'Desactivadas'} onPress={() => p.onSeccion('avisos')} />}
        <FilaNav icono="shield-checkmark-outline" titulo="Seguridad" detalle={p.biometria ? 'Huella o rostro al abrir' : 'Sin desbloqueo biométrico'} onPress={() => p.onSeccion('seguridad')} />
        <FilaNav icono="document-text-outline" titulo="Privacidad y datos" detalle="Qué guardamos y tus derechos" onPress={() => p.onSeccion('privacidad')} />
        <FilaNav icono="information-circle-outline" titulo="Acerca de Tinotify" detalle={`Versión ${p.version}`} ultima onPress={() => p.onSeccion('acerca')} />
      </Tarjeta>
      <Boton texto="Cerrar sesión" secundario icono="log-out-outline" onPress={() => { void p.onSalir(); }} />
    </>;
  }

  const volver = <Pressable accessibilityRole="button" accessibilityLabel="Volver a Ajustes" onPress={() => p.onSeccion(null)} style={s.volver}>
    <Ionicons name="chevron-back" size={22} color={colores.marino} /><Text style={s.fuerte}>Ajustes</Text></Pressable>;

  // ---- Secciones --------------------------------------------------------------------------------------------------
  if (p.seccion === 'cuenta') {
    return <>{volver}<Titulo texto="Mi cuenta" />
      {error !== '' && <Aviso texto={error} />}
      <Tarjeta>
        <Text style={s.fuerte}>¿Cómo te saludamos?</Text>
        {p.nombreSigac !== '' && p.nombre === '' && !cambiando ? <>
          <Text style={s.valor}>{primerNombre(p.nombreSigac)}</Text>
          <Texto>Tomado de tu cuenta de SIGAC. Se guarda solo en este teléfono.</Texto>
          <Boton texto="Cambiar" secundario icono="create-outline" onPress={() => { setBorrador(primerNombre(p.nombreSigac)); setCambiando(true); }} />
        </> : <>
          <Campo icono="happy-outline" etiqueta="Tu nombre (opcional)" valor={borrador} onCambio={setBorrador} palabras />
          <Boton texto="Guardar nombre" secundario icono="checkmark-outline" desactivado={borrador.trim() === p.nombre}
            onPress={() => { p.onNombre(borrador); setCambiando(false); }} />
          <Texto>{`${p.nombreSigac !== '' ? 'Déjalo vacío para volver al nombre de SIGAC. ' : 'No pudimos leerlo de SIGAC. '}Se guarda solo en este teléfono y aparece en el saludo de Inicio.`}</Texto>
        </>}
      </Tarjeta>
      {p.usuario ? <>
        <Tarjeta>
          <Text style={s.etiquetaCampo}>Correo</Text>
          <Text style={s.valor}>{p.correo ?? '—'}</Text>
        </Tarjeta>
        <Zona titulo="Zona de riesgo">
          <Boton texto="Eliminar mi cuenta" peligro icono="trash-outline" onPress={() => p.onCuenta('eliminar')} />
          <Texto>Borra tu cuenta y todos tus datos. No se puede deshacer.</Texto>
        </Zona>
      </> : <>
        <Tarjeta>
          <Text style={s.fuerte}>Invitar a una persona</Text>
          <Text style={[s.cuerpo, { marginBottom: espacio.m }]}>Genera un código de un solo uso, válido por 7 días, que compartes tú.</Text>
          <Boton texto="Crear y compartir invitación" icono="person-add-outline" onPress={() => { void invitar(); }} />
        </Tarjeta>
        <Boton texto="Enviar correo de prueba" secundario icono="mail-outline" onPress={() => { void probarElCorreo(); }} />
        <Texto>Comprueba que los códigos por correo salen por Brevo y, si falla, muestra el motivo.</Texto>
      </>}
    </>;
  }

  if (p.seccion === 'sigac') {
    return <>{volver}<Titulo texto="Conexión con SIGAC" />
      {error !== '' && <Aviso texto={error} />}
      <Tarjeta>
        <View style={s.fila}>
          <Text style={[s.fuerte, { flex: 1 }]}>Estado</Text>
          <Etiqueta texto={conectada ? 'Conectada' : 'Sin conectar'} tono={conectada ? 'lima' : 'rojo'} />
        </View>
        <Text style={s.cuerpo}>{conectada ? 'Tinotify revisa tu cuenta de SIGAC tres veces al día (7:30, 12:30 y 18:30).' : 'Aún no has conectado tu cuenta de SIGAC, así que no se revisa nada.'}</Text>
      </Tarjeta>
      <Boton texto={conectada ? 'Actualizar mi clave de SIGAC' : 'Conectar SIGAC'} icono="key-outline" onPress={p.onReconectar} />
      <Texto>Úsalo si cambiaste tu clave en SIGAC: mientras no la actualices, las revisiones fallarán.</Texto>
      {conectada && <Zona titulo="Zona de riesgo">
        <Boton texto="Desconectar mi cuenta de SIGAC" peligro icono="trash-outline" onPress={confirmarOlvidar} />
        <Texto>Borra tu usuario y clave de SIGAC y el estado de seguimiento.</Texto>
      </Zona>}
    </>;
  }

  if (p.seccion === 'avisos') {
    return <>{volver}<Titulo texto="Notificaciones" />
      {error !== '' && <Aviso texto={error} />}
      <Tarjeta><Interruptor titulo="Avisos en este teléfono" detalle="Una notificación cuando haya actuaciones nuevas o aparezca un expediente nuevo." valor={push} onCambio={cambiarPush} /></Tarjeta>
      <Boton texto="Enviar notificación de prueba" secundario icono="paper-plane-outline" onPress={() => { void probarPush(); }} />
      <Texto>Comprueba que este teléfono recibe los avisos. No modifica tus expedientes.</Texto>
      <Tarjeta>
        <Text style={s.fuerte}>Correo</Text>
        <Text style={s.cuerpo}>Si tu cuenta tiene un correo registrado, los avisos también llegan allí en el ciclo de las 7:30, 12:30 y 18:30.</Text>
      </Tarjeta>
      <Text style={s.pequeno}>Un teléfono recibe las notificaciones de una sola cuenta a la vez: la última que las active.</Text>
    </>;
  }

  if (p.seccion === 'seguridad') {
    return <>{volver}<Titulo texto="Seguridad" />
      <Tarjeta><Interruptor titulo="Huella o rostro" detalle={hayBiometria ? 'Se pide al abrir la aplicación.' : 'Configura una huella o un rostro en el teléfono para activarlo.'}
        valor={p.biometria} desactivado={!hayBiometria} onCambio={p.onBiometria} /></Tarjeta>
      <Text style={s.pequeno}>Si el sensor falla, puedes usar el PIN de tu teléfono.</Text>
    </>;
  }

  if (p.seccion === 'privacidad') {
    return <>{volver}<Titulo texto="Privacidad y datos" />
      <Tarjeta>
        <Text style={s.fuerte}>Qué guardamos</Text>
        <Text style={s.cuerpo}>Tu usuario y clave de SIGAC, cifrados; nunca en este teléfono. La lista de tus expedientes (radicado, nombre y estado), cifrada. Una ficha corta de cada actuación nueva (fecha, etapa y extracto), cifrada y por 90 días. Resúmenes cifrados para detectar cambios y conteos de cada revisión.</Text>
      </Tarjeta>
      <Tarjeta>
        <Text style={s.fuerte}>Qué no guardamos</Text>
        <Text style={s.cuerpo}>El historial completo ni los anexos de tus actuaciones: se leen de SIGAC cuando abres un expediente y no se almacenan.</Text>
      </Tarjeta>
      <Boton texto="Política de tratamiento de datos" secundario icono="open-outline" onPress={() => { void Linking.openURL(URL_POLITICA); }} />
      <View style={{ height: espacio.s }} />
      <Boton texto="Términos de uso" secundario icono="open-outline" onPress={() => { void Linking.openURL(URL_TERMINOS); }} />
    </>;
  }

  return <>{volver}<Titulo texto="Acerca de Tinotify" />
    <Tarjeta>
      <Text style={s.fuerte}>Tinotify {p.version}</Text>
      <Text style={s.cuerpo}>Tinotify no está afiliado a SIGAC. Los avisos son una ayuda: confirma siempre la información en el sistema oficial.</Text>
    </Tarjeta>
  </>;
}

function FilaNav({ icono, titulo, detalle, onPress, alerta, ultima }: { icono: Icono; titulo: string; detalle: string; onPress: () => void; alerta?: boolean; ultima?: boolean }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={`${titulo}. ${detalle}`} onPress={onPress}
    style={({ pressed }) => [s.filaNav, !ultima && s.filaNavLinea, pressed && { backgroundColor: colores.azulChip }]}>
    <View style={s.icono}><Ionicons name={icono} size={20} color={colores.marino} /></View>
    <View style={{ flex: 1 }}>
      <Text style={s.fuerte}>{titulo}</Text>
      <Text style={[s.pequeno, { marginTop: 0 }, alerta && { color: colores.error, fontWeight: '600' }]}>{detalle}</Text>
    </View>
    <Ionicons name="chevron-forward" size={20} color={colores.textoSuave} />
  </Pressable>;
}

function Interruptor({ titulo, detalle, valor, onCambio, desactivado }: { titulo: string; detalle: string; valor: boolean; onCambio: (v: boolean) => Promise<void> | void; desactivado?: boolean }) {
  return <View style={s.fila}>
    <View style={{ flex: 1 }}>
      <Text style={s.fuerte}>{titulo}</Text>
      <Text style={s.cuerpo}>{detalle}</Text>
    </View>
    <View style={{ alignItems: 'center', gap: 2, opacity: desactivado ? 0.5 : 1 }}>
      <Switch value={valor} disabled={desactivado} onValueChange={v => { void onCambio(v); }} accessibilityLabel={`${titulo}: ${valor ? 'activado' : 'desactivado'}`}
        trackColor={{ false: '#AEBBD3', true: colores.marino }} thumbColor={valor ? colores.lima : '#5B6B88'} ios_backgroundColor="#AEBBD3" />
      <Text style={[s.estadoInterruptor, { color: valor ? '#3F7D1A' : colores.textoSuave }]}>{valor ? 'Activado' : 'Desactivado'}</Text>
    </View>
  </View>;
}

const Texto = ({ children }: { children: string }) => <Text style={[s.pequeno, { marginBottom: espacio.m }]}>{children}</Text>;
const Zona = ({ titulo, children }: { titulo: string; children: React.ReactNode }) => <View style={s.zona}><Text style={s.zonaTitulo}>{titulo}</Text>{children}</View>;

const s = StyleSheet.create({
  perfil: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colores.marino, alignItems: 'center', justifyContent: 'center' },
  estadoInterruptor: { fontSize: 12, fontWeight: '700' },
  perfilNombre: { fontSize: 18, fontWeight: '700', color: colores.texto },
  filaNav: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 16, paddingVertical: 14 },
  filaNavLinea: { borderBottomWidth: 1, borderBottomColor: colores.borde },
  icono: { width: 38, height: 38, borderRadius: radios.medio, backgroundColor: colores.azulChip, alignItems: 'center', justifyContent: 'center' },
  volver: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 12 },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 6 },
  fuerte: { fontSize: 17, fontWeight: '700', color: colores.texto, marginBottom: 2 },
  cuerpo: { fontSize: 15, color: colores.textoSuave, lineHeight: 22 },
  pequeno: { fontSize: 13, color: colores.textoSuave, marginTop: 4, lineHeight: 18 },
  etiquetaCampo: { fontSize: 13, fontWeight: '700', color: colores.textoSuave, textTransform: 'uppercase', letterSpacing: 0.5 },
  valor: { fontSize: 17, color: colores.texto, marginTop: 2 },
  zona: { marginTop: espacio.xl, padding: espacio.l, borderRadius: radios.medio, borderWidth: 1, borderColor: '#E6B8B4', backgroundColor: colores.errorSuave },
  zonaTitulo: { fontSize: 13, fontWeight: '700', color: colores.error, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: espacio.m },
});
