import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, Share, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Aviso, Boton, Etiqueta, Tarjeta, TarjetaEsqueleto } from './componentes';
import { ErrorApi, adminActivo, adminBorrarDatos, adminEliminar, adminRol, adminUsuarios, crearInvitacion, type UsuarioAdmin } from './api';
import { fechaHoraBogota, resumenDeEjecucion } from './revisiones';
import { colores, espacio } from './tema';

const mensajeDe = (err: unknown) => (err instanceof ErrorApi ? err.message : 'No se completó la operación.');

/** Panel de administración: personas con cuenta, su estado y acciones. Nunca muestra claves de SIGAC ni el contenido de sus expedientes. */
export default function Admin({ token }: { token: string }) {
  const [lista, setLista] = useState<UsuarioAdmin[] | null>(null);
  const [yo, setYo] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try { const r = await adminUsuarios(token); setLista(r.usuarios); setYo(r.yo); setError(''); }
    catch (err) { setError(mensajeDe(err)); }
  }, [token]);
  useEffect(() => { void cargar(); }, [cargar]);

  async function ejecutar(id: string, accion: () => Promise<unknown>) {
    setOcupado(id);
    try { await accion(); await cargar(); } catch (err) { setError(mensajeDe(err)); } finally { setOcupado(null); }
  }

  function confirmar(titulo: string, texto: string, boton: string, accion: () => Promise<unknown>, id: string) {
    Alert.alert(titulo, texto, [
      { text: 'Cancelar', style: 'cancel' },
      { text: boton, style: 'destructive', onPress: () => { void ejecutar(id, accion); } },
    ]);
  }

  async function invitar() {
    try {
      const r = await crearInvitacion(token);
      await Share.share({ message: `Código de invitación de Tinotify (vale ${r.vigencia_dias} días y un solo uso): ${r.codigo}` });
    } catch (err) { setError(mensajeDe(err)); }
  }

  return <>
    <Boton texto="Crear invitación" icono="person-add-outline" onPress={() => { void invitar(); }} />
    <Text style={s.nota}>Cada persona se registra con su propio correo: ahí recibirá sus avisos y los códigos para recuperar su contraseña.</Text>
    {error !== '' && <Aviso texto={error} />}
    {lista === null ? <><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto lineas={3} /></> :
      lista.length === 0 ? <Tarjeta><Text style={s.cuerpo}>Todavía no hay cuentas. Crea una invitación para la primera persona.</Text></Tarjeta> :
      lista.map(u => {
        const propia = u.id === yo;
        const trabajando = ocupado === u.id;
        const etiquetaCorreo = u.correo ?? 'Cuenta sin correo visible';
        return <Tarjeta key={u.id}>
          <Text style={s.fuerte} numberOfLines={1}>{etiquetaCorreo}{propia ? ' (tú)' : ''}</Text>
          <View style={s.chips}>
            {u.es_admin && <Etiqueta texto="Administración" tono="azul" />}
            {!u.activo && <Etiqueta texto="Suspendida" tono="rojo" />}
            <Etiqueta texto={u.con_credenciales ? 'SIGAC conectado' : 'SIGAC sin conectar'} tono={u.con_credenciales ? 'lima' : 'azul'} />
          </View>
          <Text style={s.cuerpo}>{u.expedientes} {u.expedientes === 1 ? 'expediente' : 'expedientes'} en seguimiento</Text>
          <Text style={s.pequeno}>
            {u.ultima_inicio && u.ultima_resultado
              ? `Última revisión: ${fechaHoraBogota(u.ultima_inicio)} · ${resumenDeEjecucion({ inicio: u.ultima_inicio, fin: null, resultado: u.ultima_resultado, expedientes: null, novedades: null, codigo: null }).titulo}`
              : 'Sin revisiones todavía'} · Registrada {fechaHoraBogota(u.desde)}
          </Text>
          <View style={s.acciones}>
            {!propia && <Accion icono={u.activo ? 'pause-circle-outline' : 'play-circle-outline'} texto={u.activo ? 'Suspender' : 'Reactivar'} desactivado={trabajando}
              onPress={() => (u.activo
                ? confirmar('Suspender cuenta', 'La persona no podrá entrar ni recibirá avisos hasta que la reactives. No se borra nada.', 'Suspender', () => adminActivo(token, u.id, false), u.id)
                : void ejecutar(u.id, () => adminActivo(token, u.id, true)))} />}
            {!propia && <Accion icono="ribbon-outline" texto={u.es_admin ? 'Quitar administración' : 'Hacer administradora'} desactivado={trabajando}
              onPress={() => confirmar(u.es_admin ? 'Quitar administración' : 'Hacer administradora',
                u.es_admin ? 'Perderá el acceso a este panel.' : 'Podrá ver este panel, crear invitaciones y administrar cuentas.',
                'Confirmar', () => adminRol(token, u.id, !u.es_admin), u.id)} />}
            <Accion icono="refresh-circle-outline" texto={propia ? 'Vaciar mis datos' : 'Vaciar datos'} desactivado={trabajando}
              onPress={() => confirmar('Vaciar datos de seguimiento', `Se borran ${propia ? 'tu usuario y clave de SIGAC' : 'el usuario y la clave de SIGAC'} y todo el seguimiento (expedientes, novedades, avisos y revisiones). ${propia ? 'Tu' : 'Su'} cuenta de Tinotify se conserva. No se puede deshacer.`,
                'Vaciar', () => adminBorrarDatos(token, u.id), u.id)} />
            {!propia && <Accion peligro icono="trash-outline" texto="Eliminar cuenta" desactivado={trabajando}
              onPress={() => confirmar('Eliminar cuenta', 'Se borran la cuenta y todos sus datos. No se puede deshacer.', 'Eliminar', () => adminEliminar(token, u.id), u.id)} />}
          </View>
        </Tarjeta>;
      })}
    <Text style={s.nota}>Aquí solo ves el estado de cada cuenta. Nunca se muestran claves de SIGAC ni el contenido de los expedientes.</Text>
  </>;
}

function Accion({ icono, texto, onPress, peligro, desactivado }: { icono: keyof typeof Ionicons.glyphMap; texto: string; onPress: () => void; peligro?: boolean; desactivado?: boolean }) {
  const color = peligro ? colores.error : colores.marino;
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!desactivado }} onPress={desactivado ? undefined : onPress}
    style={[s.accion, peligro && { borderColor: colores.error }, desactivado && { opacity: 0.5 }]}>
    <Ionicons name={icono} size={18} color={color} /><Text style={[s.accionTxt, { color }]}>{texto}</Text>
  </Pressable>;
}

const s = StyleSheet.create({
  fuerte: { fontSize: 17, fontWeight: '700', color: colores.texto },
  cuerpo: { fontSize: 15, color: colores.textoSuave, lineHeight: 22, marginTop: 4 },
  pequeno: { fontSize: 13, color: colores.textoSuave, marginTop: 4 },
  nota: { fontSize: 13, color: colores.textoSuave, marginVertical: espacio.m },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  acciones: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  accion: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 999, borderWidth: 1, borderColor: colores.borde, backgroundColor: colores.blanco },
  accionTxt: { fontSize: 14, fontWeight: '600' },
});
