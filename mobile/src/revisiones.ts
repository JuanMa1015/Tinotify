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
