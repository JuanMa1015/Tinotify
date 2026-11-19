import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, Share, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Aviso, Boton, Etiqueta, Tarjeta, TarjetaEsqueleto } from './componentes';
import { ErrorApi, adminActivo, adminBorrarDatos, adminEliminar, adminRol, adminUsuarios, crearInvitacion, type UsuarioAdmin } from './api';
import { fechaHoraBogota, resumenDeEjecucion } from './revisiones';
import { colores, espacio } from './tema';

const mensajeDe = (err: unknown) => (err instanceof ErrorApi ? err.message : 'No se completó la operación.');

type Invitacion = { codigo: string; dias: number };

/** Panel de administración: personas con cuenta, su estado y acciones. Nunca muestra claves de SIGAC ni el contenido de sus expedientes. */
export default function Admin({ token, recarga = 0 }: { token: string; recarga?: number }) {
  const [lista, setLista] = useState<UsuarioAdmin[] | null>(null);
  const [yo, setYo] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [invitacion, setInvitacion] = useState<Invitacion | null>(null);
  const [creando, setCreando] = useState(false);

  const cargar = useCallback(async () => {
    try { const r = await adminUsuarios(token); setLista(r.usuarios); setYo(r.yo); setError(''); }
    catch (err) { setError(mensajeDe(err)); }
  }, [token]);
  useEffect(() => { void cargar(); }, [cargar, recarga]);

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

  async function crear() {
    setCreando(true);
    try { const r = await crearInvitacion(token); setInvitacion({ codigo: r.codigo, dias: r.vigencia_dias }); setError(''); }
    catch (err) { setError(mensajeDe(err)); } finally { setCreando(false); }
  }

  const compartir = (i: Invitacion) => {
    void Share.share({ message: `Te invito a Tinotify. Instala la aplicación, toca «Crear cuenta con invitación» y usa este código (vale ${i.dias} días y un solo uso): ${i.codigo}` });
  };

  const total = lista?.length ?? 0;
  const conSigac = (lista ?? []).filter(u => u.con_credenciales).length;
  const suspendidas = (lista ?? []).filter(u => !u.activo).length;

  return <>
    <View style={s.resumen}>
      <Dato valor={total} texto={total === 1 ? 'Cuenta' : 'Cuentas'} />
      <Dato valor={conSigac} texto="Con SIGAC" />
      <Dato valor={suspendidas} texto="Suspendidas" alerta={suspendidas > 0} />
    </View>

    <Tarjeta>
      <Text style={s.titulo}>Invitar a una persona</Text>
      <Text style={s.cuerpo}>Genera un código de un solo uso. La persona se registra con su propio correo: ahí recibirá sus avisos y sus códigos de acceso.</Text>
      <View style={{ height: espacio.m }} />
      <Boton texto="Crear invitación" icono="person-add-outline" onPress={() => { void crear(); }} cargando={creando} />
      {invitacion && <View style={s.codigoCaja}>
        <Text style={s.codigoEtiqueta}>CÓDIGO DE INVITACIÓN</Text>
        <Text selectable style={s.codigo}>{invitacion.codigo}</Text>
        <Text style={s.pequeno}>Vale {invitacion.dias} días y se usa una sola vez.</Text>
        <View style={{ height: espacio.s }} />
        <Boton texto="Compartir" secundario icono="share-social-outline" onPress={() => compartir(invitacion)} />
      </View>}
    </Tarjeta>

    {error !== '' && <Aviso texto={error} />}
    <Text style={s.seccion}>Cuentas</Text>
    {lista === null ? <><TarjetaEsqueleto lineas={3} /><TarjetaEsqueleto lineas={3} /></> :
      lista.length === 0 ? <Tarjeta><Text style={s.cuerpo}>Todavía no hay cuentas. Crea una invitación para la primera persona.</Text></Tarjeta> :
      lista.map(u => {
        const propia = u.id === yo;
        const trabajando = ocupado === u.id;
        const desplegada = abierta === u.id;
        const hayDatos = u.con_credenciales || u.expedientes > 0;
        return <Pressable key={u.id} accessibilityRole="button" accessibilityState={{ expanded: desplegada }} onPress={() => setAbierta(desplegada ? null : u.id)}>
          <Tarjeta estilo={!u.activo ? { opacity: 0.75 } : undefined}>
            <View style={s.fila}>
              <View style={s.avatar}><Ionicons name={u.es_admin ? 'ribbon' : 'person'} size={18} color={colores.lima} /></View>
              <View style={{ flex: 1 }}>
                <Text style={s.correo}>{u.correo ?? 'Cuenta sin correo visible'}</Text>
                <View style={s.chips}>
                  {propia && <Etiqueta texto="Tú" tono="lima" />}
                  {u.es_admin && <Etiqueta texto="Administración" tono="azul" />}
                  {!u.activo && <Etiqueta texto="Suspendida" tono="rojo" />}
                  {!u.es_admin && <Etiqueta texto={u.con_credenciales ? 'SIGAC conectado' : 'SIGAC sin conectar'} tono={u.con_credenciales ? 'lima' : 'azul'} />}
                </View>
              </View>
              <Ionicons name={desplegada ? 'chevron-up' : 'chevron-down'} size={20} color={colores.textoSuave} />
            </View>
            {desplegada && <>
              <View style={s.linea} />
              {!u.es_admin && <Detalle icono="folder-outline" texto={`${u.expedientes} ${u.expedientes === 1 ? 'expediente' : 'expedientes'} en seguimiento`} />}
              {!u.es_admin && <Detalle icono="refresh-outline" texto={u.ultima_inicio && u.ultima_resultado
                ? `Última revisión ${fechaHoraBogota(u.ultima_inicio)} · ${resumenDeEjecucion({ inicio: u.ultima_inicio, fin: null, resultado: u.ultima_resultado, expedientes: null, novedades: null, codigo: null }).titulo}`
                : 'Todavía sin revisiones'} />}
              <Detalle icono="calendar-outline" texto={`Registrada ${fechaHoraBogota(u.desde)}`} />
              <View style={s.acciones}>
                {!propia && <Accion icono={u.activo ? 'pause-circle-outline' : 'play-circle-outline'} texto={u.activo ? 'Suspender' : 'Reactivar'} desactivado={trabajando}
                  onPress={() => (u.activo
                    ? confirmar('Suspender cuenta', 'La persona no podrá entrar ni recibirá avisos hasta que la reactives. No se borra nada.', 'Suspender', () => adminActivo(token, u.id, false), u.id)
                    : void ejecutar(u.id, () => adminActivo(token, u.id, true)))} />}
                {!propia && <Accion icono="ribbon-outline" texto={u.es_admin ? 'Quitar administración' : 'Hacer administradora'} desactivado={trabajando}
                  onPress={() => confirmar(u.es_admin ? 'Quitar administración' : 'Hacer administradora',
                    u.es_admin ? 'Perderá el acceso a este panel.' : 'Podrá ver este panel, crear invitaciones y administrar cuentas.',
                    'Confirmar', () => adminRol(token, u.id, !u.es_admin), u.id)} />}
                {hayDatos && <Accion icono="refresh-circle-outline" texto={propia ? 'Vaciar mis datos' : 'Vaciar datos'} desactivado={trabajando}
                  onPress={() => confirmar('Vaciar datos de seguimiento', `Se borran ${propia ? 'tu usuario y clave de SIGAC' : 'el usuario y la clave de SIGAC'} y todo el seguimiento (expedientes, novedades, avisos y revisiones). ${propia ? 'Tu' : 'Su'} cuenta de Tinotify se conserva. No se puede deshacer.`,
                    'Vaciar', () => adminBorrarDatos(token, u.id), u.id)} />}
                {!propia && <Accion peligro icono="trash-outline" texto="Eliminar cuenta" desactivado={trabajando}
                  onPress={() => confirmar('Eliminar cuenta', 'Se borran la cuenta y todos sus datos. No se puede deshacer.', 'Eliminar', () => adminEliminar(token, u.id), u.id)} />}
              </View>
              {propia && !hayDatos && <Text style={s.pequeno}>Esta es tu cuenta. Una cuenta administradora no puede suspenderse ni borrarse a sí misma.</Text>}
            </>}
          </Tarjeta>
        </Pressable>;
      })}
    <Text style={s.nota}>Aquí solo ves el estado de cada cuenta. Nunca se muestran claves de SIGAC ni el contenido de los expedientes. Toca una cuenta para ver sus acciones.</Text>
  </>;
}

function Dato({ valor, texto, alerta }: { valor: number; texto: string; alerta?: boolean }) {
  return <View style={s.dato}>
    <Text style={[s.datoNum, alerta && { color: colores.error }]}>{valor}</Text>
    <Text style={s.datoTxt}>{texto}</Text>
  </View>;
}

function Detalle({ icono, texto }: { icono: keyof typeof Ionicons.glyphMap; texto: string }) {
  return <View style={s.detalle}><Ionicons name={icono} size={16} color={colores.textoSuave} /><Text style={s.cuerpoChico}>{texto}</Text></View>;
}

function Accion({ icono, texto, onPress, peligro, desactivado }: { icono: keyof typeof Ionicons.glyphMap; texto: string; onPress: () => void; peligro?: boolean; desactivado?: boolean }) {
  const color = peligro ? colores.error : colores.marino;
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!desactivado }} onPress={desactivado ? undefined : onPress}
    style={[s.accion, peligro && { borderColor: colores.error }, desactivado && { opacity: 0.5 }]}>
    <Ionicons name={icono} size={18} color={color} /><Text style={[s.accionTxt, { color }]}>{texto}</Text>
  </Pressable>;
}

const s = StyleSheet.create({
  resumen: { flexDirection: 'row', gap: 10, marginBottom: espacio.m },
  dato: { flex: 1, backgroundColor: colores.marino, borderRadius: 16, paddingVertical: 14, alignItems: 'center' },
  datoNum: { fontSize: 26, fontWeight: '800', color: colores.lima },
  datoTxt: { fontSize: 12, color: colores.fondo, marginTop: 2 },
  titulo: { fontSize: 17, fontWeight: '700', color: colores.texto, marginBottom: 4 },
  cuerpo: { fontSize: 15, color: colores.textoSuave, lineHeight: 22 },
  cuerpoChico: { fontSize: 14, color: colores.textoSuave, flex: 1, lineHeight: 20 },
  pequeno: { fontSize: 13, color: colores.textoSuave, marginTop: 6 },
  seccion: { fontSize: 14, fontWeight: '700', color: colores.textoSuave, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 18, marginBottom: 8 },
  nota: { fontSize: 13, color: colores.textoSuave, marginVertical: espacio.m, lineHeight: 19 },
  codigoCaja: { marginTop: espacio.m, padding: 16, borderRadius: 16, backgroundColor: colores.limaSuave, borderWidth: 1, borderColor: '#9DC356', alignItems: 'center' },
  codigoEtiqueta: { fontSize: 11, fontWeight: '800', color: colores.marino, letterSpacing: 1 },
  codigo: { fontSize: 22, fontWeight: '800', color: colores.marino, letterSpacing: 2, marginVertical: 6, textAlign: 'center' },
  fila: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: colores.marino, alignItems: 'center', justifyContent: 'center' },
  correo: { fontSize: 16, fontWeight: '700', color: colores.texto },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  linea: { height: 1, backgroundColor: colores.borde, marginVertical: 12 },
  detalle: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginBottom: 6 },
  acciones: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  accion: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 999, borderWidth: 1, borderColor: colores.borde, backgroundColor: colores.blanco },
  accionTxt: { fontSize: 14, fontWeight: '600' },
});
