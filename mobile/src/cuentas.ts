// Lógica pura de cuentas (sin red ni React): validaciones iguales a las del servidor y mensajes para personas.

export const CONSENTIMIENTO = 'consentimiento-v1';
export const URL_POLITICA = 'https://github.com/JuanMa1015/Tinotify/blob/main/docs/legal/politica-tratamiento-datos.md';
export const URL_SIGAC = 'https://sigac.udea.edu.co/sigac/';
export const URL_TERMINOS = 'https://github.com/JuanMa1015/Tinotify/blob/main/docs/legal/terminos-de-uso.md';

/** Un token `tn_…` es de una cuenta de usuario; cualquier otro es el código del propietario. */
export const esTokenDeUsuario = (token: string) => token.startsWith('tn_');

const CORREO = /^[a-z0-9._%+-]{1,64}@[a-z0-9-]+(\.[a-z0-9-]+)+$/;

export function validarCorreo(correo: string): string | null {
  const c = correo.trim().toLowerCase();
  return c.length <= 254 && CORREO.test(c) && !c.includes('..') ? null : 'Escribe un correo válido.';
}

export function validarInvitacion(invitacion: string): string | null {
  return invitacion.replace(/[\s-]/g, '').length < 8 ? 'Escribe el código de invitación que te dieron.' : null;
}

/** Qué le decimos a la persona según lo que respondió el servidor al pedir un código por correo. */
export const TEXTOS_CODIGO: Record<string, string> = {
  no_registrado: 'Ese correo no está registrado en Tinotify. Revisa que sea el mismo con el que creaste tu cuenta.',
  limite: 'Ya pediste varios códigos. Revisa tu correo (también el spam) o espera una hora para pedir otro.',
  fallo_envio: 'No pudimos enviar el correo en este momento. Inténtalo de nuevo en unos minutos; si sigue igual, avisa a quien administra Tinotify.',
  invitacion_invalida: 'Ese código de invitación no es válido o ya se usó. Pídele uno nuevo a quien administra Tinotify.',
  ya_registrado: 'Ese correo ya tiene una cuenta. Vuelve atrás y usa «Entrar».',
  correo_invalido: 'Escribe un correo válido.',
};

const CODIGOS: Record<string, string> = {
  correo_no_valido: 'Escribe un correo válido.',
  consentimiento_no_valido: 'Esta versión de la aplicación no está al día con los términos. Actualiza la aplicación.',
};

/** Mensaje claro para un error de las rutas /auth; null si no hay uno específico (se usa el genérico). */
export function mensajeDeAuth(estado: number | null, detalle?: string): string | null {
  if (detalle) {
    const codigo = detalle.startsWith('datos_no_validos:') ? detalle.slice('datos_no_validos:'.length) : detalle;
    if (CODIGOS[codigo]) return CODIGOS[codigo];
  }
  switch (estado) {
    case 400: return 'El código no es válido o ya venció. Pide uno nuevo.';
    case 401: return 'Tu sesión ya no es válida. Entra de nuevo.';
    case 429: return 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.';
    default: return null;
  }
}
