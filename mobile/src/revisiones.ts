// Lógica pura (sin red ni React): horarios del monitor y textos del estado. Las revisiones corren 7:30, 12:30 y 18:30 en Bogotá (UTC-5, sin horario de verano).

const HORAS_UTC = [[12, 30], [17, 30], [23, 30]] as const;
const ETIQUETAS_BOGOTA = ['7:30', '12:30', '18:30'] as const;

export function proximaRevision(ahora: Date): { fecha: Date; etiqueta: string } {
  for (let dia = 0; dia <= 1; dia++) {
    for (let i = 0; i < HORAS_UTC.length; i++) {
      const [h, m] = HORAS_UTC[i];
      const fecha = new Date(Date.UTC(ahora.getUTCFullYear(), ahora.getUTCMonth(), ahora.getUTCDate() + dia, h, m));
      if (fecha.getTime() > ahora.getTime()) return { fecha, etiqueta: ETIQUETAS_BOGOTA[i] };
    }
  }
  throw new Error('inalcanzable');
}

export type EstadoMonitor = {
  credenciales_guardadas: boolean;
  expedientes_en_estado: number;
  avisos_pendientes: number;
  ultima_ejecucion: { resultado: string; inicio: string; fin: string | null } | null;
};

export type Resumen = { titulo: string; detalle: string; requiereAtencion: boolean };

export function resumenDeEstado(estado: EstadoMonitor): Resumen {
  if (!estado.credenciales_guardadas) {
    return { titulo: 'Sin cuenta conectada', detalle: 'Conecta tu cuenta de SIGAC para empezar.', requiereAtencion: true };
  }
  const ultima = estado.ultima_ejecucion;
  if (!ultima) return { titulo: 'Esperando la primera revisión', detalle: 'Se hará en el próximo horario.', requiereAtencion: false };
  switch (ultima.resultado) {
    case 'ok': return { titulo: 'Todo al día', detalle: 'Sin novedades en la última revisión.', requiereAtencion: false };
    case 'linea_base': return { titulo: 'Seguimiento iniciado', detalle: 'Desde ahora te avisamos de lo nuevo.', requiereAtencion: false };
    case 'anomalia': return { titulo: 'Hay una lectura por revisar', detalle: 'Revisa SIGAC para confirmar.', requiereAtencion: true };
    case 'error_acceso': return { titulo: 'Actualiza tu clave', detalle: 'SIGAC no aceptó tus datos de acceso.', requiereAtencion: true };
    case 'error_sigac': return { titulo: 'SIGAC no respondió', detalle: 'Reintentaremos en la próxima revisión.', requiereAtencion: true };
    default: return { titulo: 'Revisión con problemas', detalle: 'Reintentaremos en la próxima revisión.', requiereAtencion: true };
  }
}

export function horaBogota(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--:--';
  return new Intl.DateTimeFormat('es-CO', { hour: 'numeric', minute: '2-digit', hour12: false, timeZone: 'America/Bogota' }).format(d);
}

export type EstadoAviso = { push: string | null; correo: string | null };
export type Ejecucion = { inicio: string; fin: string | null; resultado: string; expedientes: number | null; novedades: number | null; codigo: string | null; aviso?: EstadoAviso | null };

export type Canal = { texto: string; ok: boolean };

/** Cómo salió el aviso de una revisión, canal por canal (solo si esa revisión creó un aviso). */
export function canalesDeAviso(aviso: EstadoAviso | null | undefined): Canal[] {
  if (!aviso) return [];
  const push: Record<string, Canal> = {
    enviado: { texto: 'Notificación enviada', ok: true }, fallido: { texto: 'Notificación no entregada', ok: false },
    sin_dispositivos: { texto: 'Notificación: sin teléfonos registrados', ok: false }, no_configurado: { texto: 'Notificaciones no configuradas', ok: false } };
  const correo: Record<string, Canal> = {
    enviado: { texto: 'Correo enviado', ok: true }, fallido: { texto: 'Correo no enviado', ok: false }, desactivado: { texto: 'Correo desactivado', ok: false } };
  const salida: Canal[] = [];
  if (aviso.push && push[aviso.push]) salida.push(push[aviso.push]);
  salida.push(aviso.correo && correo[aviso.correo] ? correo[aviso.correo] : { texto: 'Correo en espera del próximo envío', ok: true });
  return salida;
}


const ZONA = 'America/Bogota';
const partes = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: ZONA, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);

/** "Hoy, 1:33 a. m." · "Ayer, 12:30 p. m." · "15 nov, 7:30 a. m." (hora de Bogotá). */
export function fechaHoraBogota(iso: string, ahora: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--';
  const hora = new Intl.DateTimeFormat('es-CO', { timeZone: ZONA, hour: 'numeric', minute: '2-digit', hour12: true }).format(d)
    .replace(/[  ]/g, ' ').toLowerCase();
  const dia = partes(d), hoy = partes(ahora), ayer = partes(new Date(ahora.getTime() - 86400000));
  const etiqueta = dia === hoy ? 'Hoy' : dia === ayer ? 'Ayer'
    : new Intl.DateTimeFormat('es-CO', { timeZone: ZONA, day: 'numeric', month: 'short' }).format(d).replace('.', '').replace(' de ', ' ');
  return `${etiqueta}, ${hora}`;
}

export function duracionTexto(inicio: string, fin: string | null): string | null {
  if (!fin) return null;
  const s = Math.round((new Date(fin).getTime() - new Date(inicio).getTime()) / 1000);
  if (!Number.isFinite(s) || s < 0) return null;
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

export function resumenDeEjecucion(e: Ejecucion): { titulo: string; detalle: string; ok: boolean } {
  const base = resumenDeEstado({ credenciales_guardadas: true, expedientes_en_estado: 0, avisos_pendientes: 0, ultima_ejecucion: { resultado: e.resultado, inicio: e.inicio, fin: e.fin } });
  const partesDetalle: string[] = [];
  if (e.expedientes !== null) partesDetalle.push(`${e.expedientes} ${e.expedientes === 1 ? 'expediente revisado' : 'expedientes revisados'}`);
  if (e.novedades) partesDetalle.push(`${e.novedades} ${e.novedades === 1 ? 'actuación nueva' : 'actuaciones nuevas'}`);
  if (e.resultado === 'en_curso') return { titulo: 'Revisión en curso', detalle: 'Aún no ha terminado.', ok: true };
  return { titulo: base.titulo, detalle: partesDetalle.join(' · ') || base.detalle, ok: !base.requiereAtencion };
}
