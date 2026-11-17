import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colores, radios, espacio } from './tema';

export type Icono = keyof typeof Ionicons.glyphMap;

export function Boton({ texto, onPress, cargando, desactivado, secundario, icono }: {
  texto: string; onPress: () => void; cargando?: boolean; desactivado?: boolean; secundario?: boolean; icono?: Icono;
}) {
  const inactivo = desactivado || cargando;
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!inactivo, busy: !!cargando }} onPress={inactivo ? undefined : onPress}
    style={({ pressed }) => [e.boton, secundario ? e.botonSec : e.botonPri, inactivo && e.botonOff, pressed && { opacity: 0.85 }]}>
    {cargando ? <ActivityIndicator color={secundario ? colores.marino : colores.blanco} /> : <>
      <Text style={[e.botonTxt, secundario && { color: colores.marino }]}>{texto}</Text>
      {icono && <Ionicons name={icono} size={20} color={secundario ? colores.marino : colores.lima} />}
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

export function BarraInferior({ activa, onElegir }: { activa: string; onElegir: (id: string) => void }) {
  const items: { id: string; texto: string; icono: Icono }[] = [
    { id: 'inicio', texto: 'Inicio', icono: 'home-outline' }, { id: 'casos', texto: 'Casos', icono: 'folder-outline' },
    { id: 'actividad', texto: 'Actividad', icono: 'refresh-outline' }, { id: 'ajustes', texto: 'Ajustes', icono: 'settings-outline' },
  ];
  return <View style={e.barra} accessibilityRole="tablist">
    {items.map(i => {
      const on = i.id === activa;
      return <Pressable key={i.id} accessibilityRole="tab" accessibilityState={{ selected: on }} onPress={() => onElegir(i.id)} style={[e.barraItem, on && e.barraItemOn]}>
        <Ionicons name={i.icono} size={22} color={on ? colores.lima : colores.fondo} />
        <Text style={[e.barraTxt, on && { color: colores.lima }]}>{i.texto}</Text>
      </Pressable>;
    })}
  </View>;
}

export const e = StyleSheet.create({
  boton: { minHeight: 52, borderRadius: radios.pildora, paddingHorizontal: 22, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  botonPri: { backgroundColor: colores.marino }, botonSec: { backgroundColor: colores.azulChip, borderWidth: 1, borderColor: colores.borde },
  botonOff: { opacity: 0.5 }, botonTxt: { color: colores.blanco, fontSize: 17, fontWeight: '600' },
  tarjeta: { backgroundColor: colores.tarjeta, borderRadius: radios.medio, padding: espacio.l, borderWidth: 1, borderColor: colores.borde, marginBottom: espacio.m },
  etiqueta: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radios.pildora }, etiquetaTxt: { fontSize: 13, fontWeight: '600' },
  titulo: { fontSize: 34, fontWeight: '700', color: colores.texto, lineHeight: 40 }, subtitulo: { fontSize: 16, color: colores.textoSuave, marginTop: 4 },
  aviso: { flexDirection: 'row', gap: 8, padding: 12, borderRadius: radios.chico, backgroundColor: colores.errorSuave, marginBottom: espacio.m, alignItems: 'center' },
  avisoTxt: { flex: 1, color: colores.error, fontSize: 14 },
  barra: { flexDirection: 'row', backgroundColor: colores.marino, borderRadius: radios.grande, marginHorizontal: 12, marginBottom: 12, padding: 6 },
  barraItem: { flex: 1, alignItems: 'center', paddingVertical: 8, borderRadius: radios.medio, gap: 2 }, barraItemOn: { backgroundColor: colores.marinoSuave },
  barraTxt: { fontSize: 12, color: colores.fondo },
});
