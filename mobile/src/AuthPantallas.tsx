import { useEffect, useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import { Image, KeyboardAvoidingView, Linking, Platform, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Aviso, Boton, Campo, CampoCodigo, Tarjeta } from './componentes';
import { guardarUltimoCorreo, leerUltimoCorreo } from './almacen';
import { ErrorApi, adminUsuarios, eliminarCuenta, entrar, pedirCodigoAcceso, pedirCodigoRegistro, registrar } from './api';
import { TEXTOS_CODIGO, URL_POLITICA, URL_TERMINOS, mensajeDeAuth, validarCorreo, validarInvitacion } from './cuentas';
import { colores, espacio } from './tema';

const mensaje = (err: unknown) => (err instanceof ErrorApi ? (mensajeDeAuth(err.estado, err.detalle) ?? err.message) : 'No se completó la operación.');

function Marco({ children }: { children: React.ReactNode }) {
  return <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} keyboardShouldPersistTaps="handled">{children}</ScrollView>
  </KeyboardAvoidingView>;
}

/** Cuenta atrás para poder pedir otro código (30 s). */
function useEspera() {
  const [espera, setEspera] = useState(0);
  useEffect(() => {
    if (espera <= 0) return;
    const t = setTimeout(() => setEspera(e => e - 1), 1000);
    return () => clearTimeout(t);
  }, [espera]);
  return [espera, () => setEspera(30)] as const;
}

function Paso({ n, de, texto }: { n: number; de: number; texto: string }) {
  return <Text style={s.paso}>PASO {n} DE {de} · {texto.toUpperCase()}</Text>;
}

/** Paso del código: dónde se envió, el campo (se envía solo al completar los 6 dígitos) y cómo pedir otro o cambiar de correo. */
function PasoCodigo({ correo, codigo, onCodigo, espera, cargando, error, textoBoton, onConfirmar, onOtro, onCambiarCorreo, vigencia }: {
  correo: string; codigo: string; onCodigo: (c: string) => void; espera: number; cargando: boolean; error: string;
  textoBoton: string; onConfirmar: (c: string) => void; onOtro: () => void; onCambiarCorreo: () => void; vigencia: string;
}) {
  return <>
    <Tarjeta>
      <View style={s.fila}>
        <Ionicons name="mail-outline" size={28} color={colores.marino} />
        <View style={{ flex: 1 }}>
          <Text style={s.confirmacion}>Revisa tu correo</Text>
          <Text style={s.texto}>Enviamos un código de 6 dígitos a <Text style={{ fontWeight: '700' }}>{correo}</Text>. Vale {vigencia}.</Text>
        </View>
      </View>
      <Text style={s.nota}>Si no lo ves en un minuto, mira en la carpeta de spam o correo no deseado.</Text>
    </Tarjeta>
    <Tarjeta>
      <CampoCodigo valor={codigo} onCambio={onCodigo} onCompleto={onConfirmar} desactivado={cargando} />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto={textoBoton} icono="paw" onPress={() => onConfirmar(codigo)} cargando={cargando} desactivado={codigo.length < 6} />
    </Tarjeta>
    <Boton texto={espera > 0 ? `Reenviar código en ${espera} s` : 'Reenviar código'} secundario icono="refresh-outline" onPress={onOtro} desactivado={espera > 0 || cargando} />
    <Text accessibilityRole="button" style={s.enlace} onPress={onCambiarCorreo}>Usar otro correo</Text>
  </>;
}

export function Bienvenida({ onLogin, onRegistro, onPropietario }: { onLogin: () => void; onRegistro: () => void; onPropietario: () => void }) {
  return <Marco>
    <View style={s.marca}>
      <Image source={require('../assets/logo-completo.png')} accessibilityLabel="Tinotify" resizeMode="contain" style={{ width: 240, height: 160 }} />
      <Text style={s.lema}>Te avisamos cuando haya novedades en tus expedientes de SIGAC</Text>
    </View>
    <Boton texto="Entrar" icono="log-in-outline" onPress={onLogin} />
    <View style={{ height: espacio.m }} />
    <Boton texto="Crear cuenta con invitación" secundario icono="mail-open-outline" onPress={onRegistro} />
    <Text style={s.nota}>No necesitas una contraseña: te enviamos un código a tu correo cada vez que entras en un teléfono nuevo.</Text>
    <Text accessibilityRole="button" style={s.enlace} onPress={onPropietario}>Acceso del propietario</Text>
    <Text style={s.nota}>El registro es solo por invitación. Pídele el código a quien administra Tinotify.</Text>
  </Marco>;
}

export function Login({ onListo, onVolver }: { onListo: (token: string, correo: string) => Promise<void>; onVolver: () => void }) {
  const [correo, setCorreo] = useState('');
  const [codigo, setCodigo] = useState('');
  const [enviado, setEnviado] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [espera, reiniciarEspera] = useEspera();
  const limpio = correo.trim().toLowerCase();
  useEffect(() => { void leerUltimoCorreo().then(c => { if (c) setCorreo(prev => prev || c); }).catch(() => undefined); }, []);

  async function pedir() {
    const falla = validarCorreo(correo);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try {
      const r = await pedirCodigoAcceso(limpio);
      if (r.estado === 'enviado') { setEnviado(true); setCodigo(''); reiniciarEspera(); } else setError(TEXTOS_CODIGO[r.estado] ?? TEXTOS_CODIGO.fallo_envio);
    } catch (err) { setError(mensaje(err)); } finally { setCargando(false); }
  }

  async function confirmar(c = codigo) {
    if (cargando || c.length < 6) return;
    setCargando(true); setError('');
    try { const r = await entrar(limpio, c); await guardarUltimoCorreo(limpio); await onListo(r.token, limpio); }
    catch (err) { setError(err instanceof ErrorApi && err.estado === 400 ? 'El código no es válido o ya venció. Pide uno nuevo.' : mensaje(err)); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Entrar</Text>
    <Paso n={enviado ? 2 : 1} de={2} texto={enviado ? 'Escribe el código' : 'Tu correo'} />
    {!enviado ? <>
      <Text style={s.nota}>Escribe el correo con el que creaste tu cuenta. Te enviamos un código de 6 dígitos; no hace falta contraseña.</Text>
      <Tarjeta>
        <Campo icono="mail-outline" etiqueta="Correo" valor={correo} onCambio={setCorreo} teclado="email-address" />
        {error !== '' && <Aviso texto={error} />}
        <Boton texto="Enviarme el código" icono="mail-outline" onPress={() => { void pedir(); }} cargando={cargando} desactivado={correo.trim() === ''} />
      </Tarjeta>
    </> : <PasoCodigo correo={limpio} codigo={codigo} onCodigo={setCodigo} espera={espera} cargando={cargando} error={error} vigencia="15 minutos"
      textoBoton="Entrar" onConfirmar={c => { void confirmar(c); }} onOtro={() => { void pedir(); }} onCambiarCorreo={() => { setEnviado(false); setCodigo(''); setError(''); }} />}
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
  </Marco>;
}

export function Registro({ onListo, onVolver }: { onListo: (token: string, correo: string) => Promise<void>; onVolver: () => void }) {
  const [invitacion, setInvitacion] = useState('');
  const [correo, setCorreo] = useState('');
  const [codigo, setCodigo] = useState('');
  const [aceptoPolitica, setAceptoPolitica] = useState(false);
  const [aceptoSigac, setAceptoSigac] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [espera, reiniciarEspera] = useEspera();
  const limpio = correo.trim().toLowerCase();

  async function pedir() {
    const falla = validarInvitacion(invitacion) ?? validarCorreo(correo)
      ?? (!aceptoPolitica ? 'Debes aceptar la política de datos y los términos de uso.' : null)
      ?? (!aceptoSigac ? 'Debes autorizar la consulta de SIGAC para poder usar Tinotify.' : null);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try {
      const r = await pedirCodigoRegistro(limpio, invitacion.trim());
      if (r.estado === 'enviado') { setEnviado(true); setCodigo(''); reiniciarEspera(); } else setError(TEXTOS_CODIGO[r.estado] ?? TEXTOS_CODIGO.fallo_envio);
    } catch (err) { setError(mensaje(err)); } finally { setCargando(false); }
  }

  async function confirmar(c = codigo) {
    if (cargando || c.length < 6) return;
    setCargando(true); setError('');
    try { const r = await registrar({ invitacion: invitacion.trim(), correo: limpio, codigo: c }); await guardarUltimoCorreo(limpio); await onListo(r.token, limpio); }
    catch (err) { setError(err instanceof ErrorApi && err.estado === 400 ? 'El código no es válido o ya venció. Pide uno nuevo.' : mensaje(err)); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Crear cuenta</Text>
    <Paso n={enviado ? 2 : 1} de={2} texto={enviado ? 'Verifica tu correo' : 'Tus datos'} />
    {!enviado ? <>
      <Text style={s.nota}>Antes de empezar: guardamos tu usuario y clave de SIGAC cifrados y entramos a SIGAC por ti tres veces al día. No guardamos el historial de tus actuaciones; sí la lista de tus expedientes (radicado, nombre y estado) y, por 90 días, una ficha corta de cada actuación nueva, todo cifrado. Puedes borrar todo cuando quieras.</Text>
      <Tarjeta>
        <Campo icono="ticket-outline" etiqueta="Código de invitación" valor={invitacion} onCambio={setInvitacion} mayusculas />
        <Campo icono="mail-outline" etiqueta="Correo (aquí recibirás tus avisos)" valor={correo} onCambio={setCorreo} teclado="email-address" />
        <View style={s.fila}>
          <Switch value={aceptoPolitica} onValueChange={setAceptoPolitica} accessibilityLabel="Acepto la política de datos y los términos"
            trackColor={{ false: '#AEBBD3', true: colores.marino }} thumbColor={aceptoPolitica ? colores.lima : '#5B6B88'} />
          <Text style={s.texto}>Acepto la <Text style={s.enlaceEnLinea} onPress={() => { void Linking.openURL(URL_POLITICA); }}>política de tratamiento de datos</Text> y los <Text style={s.enlaceEnLinea} onPress={() => { void Linking.openURL(URL_TERMINOS); }}>términos de uso</Text>.</Text>
        </View>
        <View style={s.fila}>
          <Switch value={aceptoSigac} onValueChange={setAceptoSigac} accessibilityLabel="Autorizo la consulta de SIGAC"
            trackColor={{ false: '#AEBBD3', true: colores.marino }} thumbColor={aceptoSigac ? colores.lima : '#5B6B88'} />
          <Text style={s.texto}>Autorizo a Tinotify a guardar mis datos de acceso cifrados y a consultar SIGAC por mí, incluida la transferencia de datos a proveedores fuera de Colombia.</Text>
        </View>
        {error !== '' && <Aviso texto={error} />}
        <Boton texto="Continuar" icono="arrow-forward" onPress={() => { void pedir(); }} cargando={cargando} />
      </Tarjeta>
    </> : <PasoCodigo correo={limpio} codigo={codigo} onCodigo={setCodigo} espera={espera} cargando={cargando} error={error} vigencia="10 minutos"
      textoBoton="Crear mi cuenta" onConfirmar={c => { void confirmar(c); }} onOtro={() => { void pedir(); }} onCambiarCorreo={() => { setEnviado(false); setCodigo(''); setError(''); }} />}
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
    <Text style={s.nota}>Tinotify no está afiliado a SIGAC. Los avisos son una ayuda: confirma siempre en el sistema oficial.</Text>
  </Marco>;
}

/** Acceso del propietario: solo el código de acceso del servidor (no es una cuenta ni lleva datos de SIGAC). */
export function AccesoPropietario({ onListo, onVolver }: { onListo: (token: string) => Promise<void>; onVolver: () => void }) {
  const [codigo, setCodigo] = useState('');
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    setCargando(true); setError('');
    try { await adminUsuarios(codigo.trim()); await onListo(codigo.trim()); }   // la lista de cuentas solo se abre con el código correcto
    catch (err) { setError(err instanceof ErrorApi && err.estado === 401 ? 'Ese código no es correcto.' : mensaje(err)); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Acceso del propietario</Text>
    <Text style={s.nota}>Escribe el código de acceso del propietario. Entras al panel de administración; no se piden datos de SIGAC.</Text>
    <Tarjeta>
      <Campo icono="key-outline" etiqueta="Código de acceso del propietario" valor={codigo} onCambio={setCodigo} secreto />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Entrar" icono="log-in-outline" onPress={() => { void enviar(); }} cargando={cargando} desactivado={codigo.trim() === ''} />
    </Tarjeta>
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
  </Marco>;
}

export function EliminarCuenta({ token, onEliminada, onCancelar }: { token: string; onEliminada: () => Promise<void>; onCancelar: () => void }) {
  const [correo, setCorreo] = useState('');
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    setCargando(true); setError('');
    try { await eliminarCuenta(token, correo.trim().toLowerCase()); await onEliminada(); }
    catch (err) { setError(err instanceof ErrorApi && err.estado === 400 ? 'Ese correo no coincide con el de tu cuenta.' : mensaje(err)); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Eliminar mi cuenta</Text>
    <Text style={s.nota}>Se borran tu cuenta, tu usuario y clave de SIGAC, la lista de tus expedientes, tu historial y tus avisos. No se puede deshacer.</Text>
    <Tarjeta>
      <Campo icono="mail-outline" etiqueta="Escribe tu correo para confirmar" valor={correo} onCambio={setCorreo} teclado="email-address" />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Eliminar definitivamente" icono="trash-outline" onPress={() => { void enviar(); }} cargando={cargando} desactivado={correo.trim() === ''} />
      <View style={{ height: espacio.s }} />
      <Boton texto="Cancelar" secundario onPress={onCancelar} desactivado={cargando} />
    </Tarjeta>
  </Marco>;
}

const s = StyleSheet.create({
  confirmacion: { fontSize: 18, fontWeight: '700', color: colores.marino, marginBottom: 2 },
  paso: { fontSize: 12, fontWeight: '800', color: colores.marinoSuave, letterSpacing: 0.8, marginBottom: espacio.s },
  pagina: { padding: 20, paddingTop: 56, paddingBottom: 32 },
  marca: { alignItems: 'center', marginBottom: espacio.xl },
  lema: { fontSize: 16, color: colores.textoSuave, textAlign: 'center', marginTop: 6 },
  titulo: { fontSize: 32, fontWeight: '700', color: colores.texto, marginBottom: espacio.m },
  enlace: { textAlign: 'center', color: colores.marinoSuave, fontSize: 16, fontWeight: '600', marginTop: 18, textDecorationLine: 'underline', paddingVertical: 8 },
  enlaceEnLinea: { color: colores.marinoSuave, fontWeight: '600', textDecorationLine: 'underline' },
  nota: { fontSize: 14, color: colores.textoSuave, marginVertical: espacio.s, lineHeight: 20 },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: espacio.l }, texto: { flex: 1, fontSize: 14, color: colores.texto, lineHeight: 20 },
});
