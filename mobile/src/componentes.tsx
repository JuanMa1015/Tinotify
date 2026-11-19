import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { ActivityIndicator, Animated, Image, Pressable, StyleSheet, Text, TextInput, View, type ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colores, radios, espacio } from './tema';

export type Icono = keyof typeof Ionicons.glyphMap;

export function Boton({ texto, onPress, cargando, desactivado, secundario, icono, peligro }: {
  texto: string; onPress: () => void; cargando?: boolean; desactivado?: boolean; secundario?: boolean; icono?: Icono; peligro?: boolean;
}) {
  const inactivo = desactivado || cargando;
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!inactivo, busy: !!cargando }} onPress={inactivo ? undefined : onPress}
    style={({ pressed }) => [e.boton, peligro ? e.botonPeligro : secundario ? e.botonSec : e.botonPri, inactivo && e.botonOff, desactivado && !cargando && e.botonApagado, pressed && { opacity: 0.85 }]}>
    {cargando ? <ActivityIndicator color={secundario ? colores.marino : colores.blanco} /> : <>
      <Text style={[e.botonTxt, secundario && { color: colores.marino }, peligro && { color: colores.error }, desactivado && { color: '#6B7A94' }]}>{texto}</Text>
      {icono && <Ionicons name={icono} size={20} color={desactivado ? '#6B7A94' : peligro ? colores.error : secundario ? colores.marino : colores.lima} />}
    </>}
  </Pressable>;
}

export function Tarjeta({ children, oscura, estilo }: { children: ReactNode; oscura?: boolean; estilo?: ViewStyle }) {
  return <View style={[e.tarjeta, oscura && { backgroundColor: colores.marino, borderColor: colores.marino }, estilo]}>{children}</View>;
}

export function Etiqueta({ texto, tono }: { texto: string; tono: 'lima' | 'azul' | 'rojo' }) {
  const fondo = tono === 'lima' ? colores.limaSuave : tono === 'rojo' ? colores.errorSuave : colores.azulChip;
  const color = tono === 'rojo' ? colores.error : colores.marino;
  return <View style={[e.etiqueta, { backgroundColor: fondo }]}><Text style={[e.etiquetaTxt, { color }]}>{texto}</Text></View>;
}

export function Titulo({ texto, subtitulo }: { texto: string; subtitulo?: string }) {
  return <View style={{ marginBottom: espacio.l }}>
    <Text accessibilityRole="header" style={e.titulo}>{texto}</Text>
    {subtitulo && <Text style={e.subtitulo}>{subtitulo}</Text>}
  </View>;
}

export function Aviso({ texto }: { texto: string }) {
  return <View accessibilityLiveRegion="polite" style={e.aviso}><Ionicons name="alert-circle" size={18} color={colores.error} /><Text style={e.avisoTxt}>{texto}</Text></View>;
}

export function BarraInferior({ activa, onElegir, insignias }: { activa: string; onElegir: (id: string) => void; insignias?: Record<string, number> }) {
  const items: { id: string; texto: string; icono: Icono }[] = [
    { id: 'inicio', texto: 'Inicio', icono: 'home-outline' }, { id: 'casos', texto: 'Casos', icono: 'folder-outline' },
    { id: 'novedades', texto: 'Novedades', icono: 'notifications-outline' },
    { id: 'actividad', texto: 'Actividad', icono: 'refresh-outline' }, { id: 'ajustes', texto: 'Ajustes', icono: 'settings-outline' },
  ];
  return <View style={e.barra} accessibilityRole="tablist">
    {items.map(i => {
      const on = i.id === activa;
      return <Pressable key={i.id} accessibilityRole="tab" accessibilityState={{ selected: on }} onPress={() => onElegir(i.id)} style={[e.barraItem, on && e.barraItemOn]}>
        <View>
          <Ionicons name={i.icono} size={22} color={on ? colores.lima : colores.fondo} />
          {!!insignias?.[i.id] && <View accessibilityLabel={`${insignias[i.id]} sin ver`} style={e.insignia}><Text style={e.insigniaTxt}>{insignias[i.id] > 99 ? '99+' : insignias[i.id]}</Text></View>}
        </View>
        <Text style={[e.barraTxt, on && { color: colores.lima }]}>{i.texto}</Text>
      </Pressable>;
    })}
  </View>;
}

export function Campo({ icono, etiqueta, valor, onCambio, secreto, teclado, mayusculas, palabras, verContrasena, visible, derecha }: {
  icono: Icono; etiqueta: string; valor: string; onCambio: (v: string) => void; secreto?: boolean;
  teclado?: 'default' | 'email-address'; mayusculas?: boolean; palabras?: boolean; verContrasena?: () => void; visible?: boolean; derecha?: ReactNode;
}) {
  return <View style={e.campo}>
    <Ionicons name={icono} size={20} color={colores.textoSuave} />
    <TextInput accessibilityLabel={etiqueta} placeholder={etiqueta} placeholderTextColor={colores.textoSuave} value={valor} onChangeText={onCambio}
      secureTextEntry={secreto} keyboardType={teclado ?? 'default'} autoCapitalize={mayusculas ? 'characters' : palabras ? 'words' : 'none'} autoCorrect={false}
      autoComplete="off" importantForAutofill="no" spellCheck={false} contextMenuHidden={secreto} style={e.entrada} />
    {verContrasena
      ? <Pressable accessibilityRole="button" accessibilityLabel={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'} onPress={verContrasena} hitSlop={12}>
          <Ionicons name={visible ? 'eye-off-outline' : 'eye-outline'} size={22} color={colores.textoSuave} /></Pressable>
      : derecha}
  </View>;
}

export function Esqueleto({ alto = 20, ancho = '100%', estilo }: { alto?: number; ancho?: number | `${number}%`; estilo?: ViewStyle }) {
  const opacidad = useRef(new Animated.Value(0.45)).current;
  useEffect(() => {
    const anim = Animated.loop(Animated.sequence([
      Animated.timing(opacidad, { toValue: 1, duration: 700, useNativeDriver: true }),
      Animated.timing(opacidad, { toValue: 0.45, duration: 700, useNativeDriver: true })]));
    anim.start();
    return () => anim.stop();
  }, [opacidad]);
  return <Animated.View accessible={false} style={[{ height: alto, width: ancho, borderRadius: radios.chico, backgroundColor: colores.borde, opacity: opacidad }, estilo]} />;
}

export function TarjetaEsqueleto({ lineas = 2 }: { lineas?: number }) {
  return <View accessibilityLabel="Cargando" style={e.tarjeta}>
    {Array.from({ length: lineas }, (_, i) => <Esqueleto key={i} alto={i === 0 ? 22 : 16} ancho={i === 0 ? '55%' : '85%'} estilo={{ marginBottom: 10 }} />)}
  </View>;
}

export function PantallaCarga({ texto }: { texto?: string }) {
  return <View accessibilityLiveRegion="polite" style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 }}>
    <Image source={require('../assets/logo-completo.png')} accessibilityLabel="Tinotify" resizeMode="contain" style={{ width: 240, height: 160 }} />
    <ActivityIndicator color={colores.marino} style={{ marginTop: 16 }} />
    {texto && <Text style={{ color: colores.textoSuave, fontSize: 15, marginTop: 12, textAlign: 'center' }}>{texto}</Text>}
  </View>;
}

export const e = StyleSheet.create({
  campo: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: colores.borde, borderRadius: radios.pildora, paddingHorizontal: 16, backgroundColor: colores.superficie, marginBottom: espacio.m, minHeight: 52 },
  entrada: { flex: 1, fontSize: 16, color: colores.texto, paddingVertical: 12 },
  boton: { minHeight: 52, borderRadius: radios.pildora, paddingHorizontal: 22, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  botonPri: { backgroundColor: colores.marino }, botonSec: { backgroundColor: colores.azulChip, borderWidth: 1, borderColor: colores.borde },
  botonPeligro: { backgroundColor: colores.blanco, borderWidth: 1, borderColor: colores.error }, botonOff: { opacity: 0.5 }, botonApagado: { opacity: 1, backgroundColor: '#E1E7F2', borderWidth: 1, borderColor: '#B9C4D8', borderStyle: 'dashed' }, botonTxt: { color: colores.blanco, fontSize: 17, fontWeight: '600' },
  tarjeta: { backgroundColor: colores.tarjeta, borderRadius: radios.medio, padding: espacio.l, borderWidth: 1, borderColor: colores.borde, marginBottom: espacio.m },
  etiqueta: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radios.pildora }, etiquetaTxt: { fontSize: 13, fontWeight: '600' },
  titulo: { fontSize: 34, fontWeight: '700', color: colores.texto, lineHeight: 40 }, subtitulo: { fontSize: 16, color: colores.textoSuave, marginTop: 4 },
  aviso: { flexDirection: 'row', gap: 8, padding: 12, borderRadius: radios.chico, backgroundColor: colores.errorSuave, marginBottom: espacio.m, alignItems: 'center' },
  avisoTxt: { flex: 1, color: colores.error, fontSize: 14 },
  barra: { flexDirection: 'row', backgroundColor: colores.marino, borderRadius: radios.grande, marginHorizontal: 12, marginBottom: 12, padding: 6 },
  barraItem: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: radios.medio, gap: 2 }, barraItemOn: { backgroundColor: colores.marinoSuave },
  barraTxt: { fontSize: 12, color: colores.fondo },
  insignia: { position: 'absolute', top: -5, right: -10, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colores.lima, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  insigniaTxt: { fontSize: 11, fontWeight: '800', color: colores.marino },
});
