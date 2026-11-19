import { useEffect, useState } from 'react';
import { Image, KeyboardAvoidingView, Linking, Platform, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { Aviso, Boton, Campo, Tarjeta } from './componentes';
import { ErrorApi, cambiarClave, eliminarCuenta, iniciarSesion, recuperacionDisponible, registrar, restablecerClave, solicitarRecuperacion } from './api';
import { URL_POLITICA, URL_TERMINOS, mensajeDeAuth, validarClave, validarCorreo, validarRegistro } from './cuentas';
import { colores, espacio } from './tema';

const TEXTOS_RECUPERACION: Record<string, string> = {
  no_registrado: 'Ese correo no está registrado en Tinotify. Revisa que sea el mismo con el que creaste tu cuenta.',
  limite: 'Ya pediste varios códigos. Revisa tu correo (también el spam) o espera una hora para pedir otro.',
  fallo_envio: 'No pudimos enviar el correo en este momento. Inténtalo de nuevo en unos minutos; si sigue igual, avisa a quien administra Tinotify.',
};

const mensaje = (err: unknown) => (err instanceof ErrorApi ? (mensajeDeAuth(err.estado, err.detalle) ?? err.message) : 'No se completó la operación.');

function Marco({ children }: { children: React.ReactNode }) {
  return <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} keyboardShouldPersistTaps="handled">{children}</ScrollView>
  </KeyboardAvoidingView>;
}

export function Bienvenida({ onLogin, onRegistro, onPropietario }: { onLogin: () => void; onRegistro: () => void; onPropietario: () => void }) {
  return <Marco>
    <View style={s.marca}>
      <Image source={require('../assets/logo-completo.png')} accessibilityLabel="Tinotify" resizeMode="contain" style={{ width: 240, height: 160 }} />
      <Text style={s.lema}>Te avisamos cuando haya novedades en tus expedientes de SIGAC</Text>
    </View>
    <Boton texto="Iniciar sesión" icono="log-in-outline" onPress={onLogin} />
    <View style={{ height: espacio.m }} />
    <Boton texto="Crear cuenta con invitación" secundario icono="mail-open-outline" onPress={onRegistro} />
    <Text style={s.nota}>Entras con el correo y la contraseña de tu cuenta de Tinotify. Tu usuario y clave de SIGAC se piden una sola vez, después de entrar.</Text>
    <Text accessibilityRole="button" style={s.enlace} onPress={onPropietario}>Acceso del propietario</Text>
    <Text style={s.nota}>El registro es solo por invitación. Pídele el código a quien administra Tinotify.</Text>
  </Marco>;
}

export function Login({ onListo, onVolver, onOlvide }: { onListo: (token: string, correo: string) => Promise<void>; onVolver: () => void; onOlvide: () => void }) {
  const [correo, setCorreo] = useState('');
  const [puedeRecuperar, setPuedeRecuperar] = useState(false);
  useEffect(() => { recuperacionDisponible().then(r => setPuedeRecuperar(r.disponible), () => undefined); }, []);
  const [clave, setClave] = useState('');
  const [ver, setVer] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    const falla = validarCorreo(correo);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try {
      const r = await iniciarSesion(correo.trim().toLowerCase(), clave);
      await onListo(r.token, correo.trim().toLowerCase());
    } catch (err) { setError(mensaje(err)); }
    finally { setClave(''); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Iniciar sesión</Text>
    <Text style={s.nota}>Usa el correo y la contraseña de tu cuenta de Tinotify, los que creaste al registrarte. No son los de SIGAC: esos se piden una sola vez, después de entrar.</Text>
    <Tarjeta>
      <Campo icono="mail-outline" etiqueta="Correo" valor={correo} onCambio={setCorreo} teclado="email-address" />
      <Campo icono="lock-closed-outline" etiqueta="Contraseña" valor={clave} onCambio={setClave} secreto={!ver} verContrasena={() => setVer(!ver)} visible={ver} />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Entrar" icono="paw" onPress={() => { void enviar(); }} cargando={cargando} desactivado={correo.trim() === '' || clave === ''} />
    </Tarjeta>
    {puedeRecuperar && <Text accessibilityRole="button" style={s.enlace} onPress={onOlvide}>¿Olvidaste tu contraseña?</Text>}
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
  </Marco>;
}

export function RecuperarClave({ onListo, onVolver }: { onListo: () => void; onVolver: () => void }) {
  const [correo, setCorreo] = useState('');
  const [codigo, setCodigo] = useState('');
  const [nueva, setNueva] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [enviado, setEnviado] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const [espera, setEspera] = useState(0);  // segundos antes de poder pedir otro código
  useEffect(() => {
    if (espera <= 0) return;
    const t = setTimeout(() => setEspera(e => e - 1), 1000);
    return () => clearTimeout(t);
  }, [espera]);

  async function pedir() {
    const falla = validarCorreo(correo);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try {
      const r = await solicitarRecuperacion(correo.trim().toLowerCase());
      if (r.estado === 'enviado') { setEnviado(true); setEspera(30); }
      else setError(TEXTOS_RECUPERACION[r.estado] ?? 'No se pudo enviar el código. Inténtalo de nuevo en unos minutos.');
    } catch (err) { setError(mensaje(err)); }
    finally { setCargando(false); }
  }

  async function cambiar() {
    const falla = validarClave(nueva, correo) ?? (nueva !== confirmar ? 'Las contraseñas no coinciden.' : null);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try { await restablecerClave(correo.trim().toLowerCase(), codigo.trim(), nueva); onListo(); }
    catch (err) {
      setError(err instanceof ErrorApi && err.estado === 400 ? 'El código no es válido o ya venció. Pide uno nuevo.' : mensaje(err));
    } finally { setNueva(''); setConfirmar(''); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Recuperar contraseña</Text>
    {!enviado ? <>
      <Text style={s.nota}>Escribe el correo de tu cuenta de Tinotify. Si está registrado, te enviamos un código de un solo uso que vale 15 minutos.</Text>
      <Tarjeta>
        <Campo icono="mail-outline" etiqueta="Correo" valor={correo} onCambio={setCorreo} teclado="email-address" />
        {error !== '' && <Aviso texto={error} />}
        <Boton texto="Enviar código" icono="mail-outline" onPress={() => { void pedir(); }} cargando={cargando} desactivado={correo.trim() === ''} />
      </Tarjeta>
    </> : <>
      <Tarjeta estilo={{ backgroundColor: colores.limaSuave, borderColor: '#9DC356' }}>
        <Text style={s.confirmacion}>✓ Te enviamos un código a {correo.trim().toLowerCase()}</Text>
        <Text style={s.nota}>Revisa también la carpeta de spam. Vale 15 minutos.</Text>
      </Tarjeta>
      <Text style={s.nota}>Escríbelo aquí con tu contraseña nueva. Al cambiarla se cierra la sesión en todos tus dispositivos.</Text>
      <Tarjeta>
        <Campo icono="keypad-outline" etiqueta="Código del correo" valor={codigo} onCambio={setCodigo} mayusculas />
        <Campo icono="key-outline" etiqueta="Contraseña nueva" valor={nueva} onCambio={setNueva} secreto />
        <Campo icono="key-outline" etiqueta="Repite la nueva" valor={confirmar} onCambio={setConfirmar} secreto />
        {error !== '' && <Aviso texto={error} />}
        <Boton texto="Cambiar contraseña" onPress={() => { void cambiar(); }} cargando={cargando} desactivado={codigo.trim() === '' || nueva === ''} />
      </Tarjeta>
      <Boton texto={espera > 0 ? `Pedir otro código (${espera} s)` : 'Pedir otro código'} secundario icono="refresh-outline"
        onPress={() => { setCodigo(''); void pedir(); }} cargando={cargando} desactivado={espera > 0} />
    </>}
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
  </Marco>;
}

export function Registro({ onListo, onVolver }: { onListo: (token: string, correo: string) => Promise<void>; onVolver: () => void }) {
  const [invitacion, setInvitacion] = useState('');
  const [correo, setCorreo] = useState('');
  const [clave, setClave] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [ver, setVer] = useState(false);
  const [aceptoPolitica, setAceptoPolitica] = useState(false);
  const [aceptoSigac, setAceptoSigac] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    const falla = validarRegistro({ invitacion, correo, clave, confirmar, aceptoPolitica, aceptoSigac });
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try {
      const r = await registrar({ invitacion: invitacion.trim(), correo: correo.trim().toLowerCase(), clave });
      await onListo(r.token, correo.trim().toLowerCase());
    } catch (err) { setError(mensaje(err)); }
    finally { setClave(''); setConfirmar(''); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Crear cuenta</Text>
    <Text style={s.nota}>Antes de empezar: guardamos tu usuario y clave de SIGAC cifrados y entramos a SIGAC por ti tres veces al día. No guardamos el historial de tus actuaciones; sí la lista de tus expedientes (radicado, nombre y estado) y, por 90 días, una ficha corta de cada actuación nueva, todo cifrado. Puedes borrar todo cuando quieras.</Text>
    <Tarjeta>
      <Campo icono="ticket-outline" etiqueta="Código de invitación" valor={invitacion} onCambio={setInvitacion} mayusculas />
      <Campo icono="mail-outline" etiqueta="Correo" valor={correo} onCambio={setCorreo} teclado="email-address" />
      <Campo icono="lock-closed-outline" etiqueta="Contraseña (10 caracteres o más)" valor={clave} onCambio={setClave} secreto={!ver} verContrasena={() => setVer(!ver)} visible={ver} />
      <Campo icono="lock-closed-outline" etiqueta="Repite la contraseña" valor={confirmar} onCambio={setConfirmar} secreto={!ver} />
      <View style={s.fila}>
        <Switch value={aceptoPolitica} onValueChange={setAceptoPolitica} accessibilityLabel="Acepto la política de datos y los términos" trackColor={{ true: colores.marino }} thumbColor={colores.blanco} />
        <Text style={s.texto}>Acepto la <Text style={s.enlaceEnLinea} onPress={() => { void Linking.openURL(URL_POLITICA); }}>política de tratamiento de datos</Text> y los <Text style={s.enlaceEnLinea} onPress={() => { void Linking.openURL(URL_TERMINOS); }}>términos de uso</Text>.</Text>
      </View>
      <View style={s.fila}>
        <Switch value={aceptoSigac} onValueChange={setAceptoSigac} accessibilityLabel="Autorizo la consulta de SIGAC" trackColor={{ true: colores.marino }} thumbColor={colores.blanco} />
        <Text style={s.texto}>Autorizo a Tinotify a guardar mis datos de acceso cifrados y a consultar SIGAC por mí, incluida la transferencia de datos a proveedores fuera de Colombia.</Text>
      </View>
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Crear cuenta" icono="paw" onPress={() => { void enviar(); }} cargando={cargando} />
    </Tarjeta>
    <Text accessibilityRole="button" style={s.enlace} onPress={onVolver}>Volver</Text>
    <Text style={s.nota}>Tinotify no está afiliado a SIGAC. Los avisos son una ayuda: confirma siempre en el sistema oficial.</Text>
  </Marco>;
}

export function CambiarClave({ token, onListo, onCancelar }: { token: string; onListo: () => void; onCancelar: () => void }) {
  const [actual, setActual] = useState('');
  const [nueva, setNueva] = useState('');
  const [confirmar, setConfirmar] = useState('');
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    const falla = validarClave(nueva) ?? (nueva !== confirmar ? 'Las contraseñas no coinciden.' : null);
    if (falla) { setError(falla); return; }
    setCargando(true); setError('');
    try { await cambiarClave(token, actual, nueva); onListo(); }
    catch (err) { setError(mensaje(err)); }
    finally { setActual(''); setNueva(''); setConfirmar(''); setCargando(false); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Cambiar contraseña</Text>
    <Text style={s.nota}>Al cambiarla, se cierra la sesión en tus otros dispositivos.</Text>
    <Tarjeta>
      <Campo icono="lock-closed-outline" etiqueta="Contraseña actual" valor={actual} onCambio={setActual} secreto />
      <Campo icono="key-outline" etiqueta="Contraseña nueva" valor={nueva} onCambio={setNueva} secreto />
      <Campo icono="key-outline" etiqueta="Repite la nueva" valor={confirmar} onCambio={setConfirmar} secreto />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Guardar" onPress={() => { void enviar(); }} cargando={cargando} desactivado={actual === '' || nueva === ''} />
      <View style={{ height: espacio.s }} />
      <Boton texto="Cancelar" secundario onPress={onCancelar} desactivado={cargando} />
    </Tarjeta>
  </Marco>;
}

export function EliminarCuenta({ token, onEliminada, onCancelar }: { token: string; onEliminada: () => Promise<void>; onCancelar: () => void }) {
  const [clave, setClave] = useState('');
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function enviar() {
    setCargando(true); setError('');
    try { await eliminarCuenta(token, clave); await onEliminada(); }
    catch (err) { setError(mensaje(err)); setCargando(false); }
    finally { setClave(''); }
  }

  return <Marco>
    <Text accessibilityRole="header" style={s.titulo}>Eliminar mi cuenta</Text>
    <Text style={s.nota}>Se borran tu cuenta, tu usuario y clave de SIGAC, la lista de tus expedientes, tu historial y tus avisos. No se puede deshacer.</Text>
    <Tarjeta>
      <Campo icono="lock-closed-outline" etiqueta="Tu contraseña" valor={clave} onCambio={setClave} secreto />
      {error !== '' && <Aviso texto={error} />}
      <Boton texto="Eliminar definitivamente" icono="trash-outline" onPress={() => { void enviar(); }} cargando={cargando} desactivado={clave === ''} />
      <View style={{ height: espacio.s }} />
      <Boton texto="Cancelar" secundario onPress={onCancelar} desactivado={cargando} />
    </Tarjeta>
  </Marco>;
}

const s = StyleSheet.create({
  confirmacion: { fontSize: 16, fontWeight: '700', color: colores.marino, marginBottom: 4 },
  pagina: { padding: 20, paddingTop: 56, paddingBottom: 32 },
  marca: { alignItems: 'center', marginBottom: espacio.xl },
  lema: { fontSize: 16, color: colores.textoSuave, textAlign: 'center', marginTop: 6 },
  titulo: { fontSize: 32, fontWeight: '700', color: colores.texto, marginBottom: espacio.m },
  enlace: { textAlign: 'center', color: colores.marinoSuave, fontSize: 16, fontWeight: '600', marginTop: 18, textDecorationLine: 'underline', paddingVertical: 8 },
  enlaceEnLinea: { color: colores.marinoSuave, fontWeight: '600', textDecorationLine: 'underline' },
  nota: { fontSize: 14, color: colores.textoSuave, marginVertical: espacio.s, lineHeight: 20 },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: espacio.l }, texto: { flex: 1, fontSize: 14, color: colores.texto, lineHeight: 20 },
});

