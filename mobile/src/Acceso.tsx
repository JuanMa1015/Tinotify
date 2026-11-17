import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Aviso, Boton, Tarjeta } from './componentes';
import { conectar, ErrorApi } from './api';
import { colores, espacio, radios } from './tema';

// Usuario y clave de SIGAC solo existen en el estado de esta pantalla mientras se escriben: se envían una vez al servidor
// (cifrado en reposo allí) y se borran siempre, con éxito o con fallo.
export default function Acceso({ onListo }: { onListo: (token: string) => Promise<void> }) {
  const [codigo, setCodigo] = useState('');
  const [usuario, setUsuario] = useState('');
  const [clave, setClave] = useState('');
  const [ver, setVer] = useState(false);
  const [autorizo, setAutorizo] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');
  const completo = codigo.trim() !== '' && usuario.trim() !== '' && clave !== '' && autorizo;

  async function enviar() {
    setCargando(true); setError('');
    const token = codigo.trim();
    try {
      await conectar(token, usuario.trim(), clave);
      await onListo(token);
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : 'No se completó la operación.');
    } finally { setClave(''); setUsuario(''); setCargando(false); }
  }

  return <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={s.pagina} keyboardShouldPersistTaps="handled">
      <View style={s.marca}>
        <View style={s.logo}><Ionicons name="paw" size={30} color={colores.lima} /></View>
        <Text style={s.nombre}>Tinotify</Text>
        <Text style={s.lema}>Te avisamos cuando haya novedades en SIGAC</Text>
      </View>
      <Tarjeta>
        <Text style={s.seccion}>Conecta tu cuenta</Text>
        <Campo icono="key-outline" etiqueta="Código de acceso del servidor" valor={codigo} onCambio={setCodigo} secreto />
        <Campo icono="person-outline" etiqueta="Usuario SIGAC" valor={usuario} onCambio={setUsuario} />
        <Campo icono="lock-closed-outline" etiqueta="Contraseña" valor={clave} onCambio={setClave} secreto={!ver}
          derecha={<Pressable accessibilityRole="button" accessibilityLabel={ver ? 'Ocultar contraseña' : 'Mostrar contraseña'} onPress={() => setVer(!ver)} hitSlop={12}>
            <Ionicons name={ver ? 'eye-off-outline' : 'eye-outline'} size={22} color={colores.textoSuave} /></Pressable>} />
        <View style={s.fila}>
          <Switch value={autorizo} onValueChange={setAutorizo} accessibilityLabel="Autorizo la consulta de SIGAC" trackColor={{ true: colores.marino }} thumbColor={colores.blanco} />
          <Text style={s.autorizo}>Autorizo a Tinotify a guardar mis datos de acceso cifrados en el servidor y a consultar SIGAC por mí 3 veces al día.</Text>
        </View>
        {error !== '' && <Aviso texto={error} />}
        <Boton texto="Conectar" icono="paw" onPress={() => { void enviar(); }} cargando={cargando} desactivado={!completo} />
      </Tarjeta>
      <Text style={s.nota}>La primera lectura puede tardar hasta 2 minutos. Tu clave se guarda cifrada en el servidor y nunca queda en el teléfono.</Text>
    </ScrollView>
  </KeyboardAvoidingView>;
}

function Campo({ icono, etiqueta, valor, onCambio, secreto, derecha }: {
  icono: keyof typeof Ionicons.glyphMap; etiqueta: string; valor: string; onCambio: (v: string) => void; secreto?: boolean; derecha?: React.ReactNode;
}) {
  return <View style={s.campo}>
    <Ionicons name={icono} size={20} color={colores.textoSuave} />
    <TextInput accessibilityLabel={etiqueta} placeholder={etiqueta} placeholderTextColor={colores.textoSuave} value={valor} onChangeText={onCambio}
      secureTextEntry={secreto} autoCapitalize="none" autoCorrect={false} autoComplete="off" importantForAutofill="no" spellCheck={false}
      contextMenuHidden={secreto} style={s.entrada} />
    {derecha}
  </View>;
}

const s = StyleSheet.create({
  pagina: { padding: 20, paddingTop: 56, paddingBottom: 32 },
  marca: { alignItems: 'center', marginBottom: espacio.xl },
  logo: { width: 64, height: 64, borderRadius: 20, backgroundColor: colores.marino, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  nombre: { fontSize: 38, fontWeight: '700', color: colores.texto }, lema: { fontSize: 16, color: colores.textoSuave, textAlign: 'center', marginTop: 6 },
  seccion: { fontSize: 20, fontWeight: '700', color: colores.texto, marginBottom: espacio.m },
  campo: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: colores.borde, borderRadius: radios.pildora, paddingHorizontal: 16, backgroundColor: colores.superficie, marginBottom: espacio.m, minHeight: 52 },
  entrada: { flex: 1, fontSize: 16, color: colores.texto, paddingVertical: 12 },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: espacio.l }, autorizo: { flex: 1, fontSize: 14, color: colores.texto },
  nota: { fontSize: 14, color: colores.textoSuave, marginTop: espacio.s },
});
