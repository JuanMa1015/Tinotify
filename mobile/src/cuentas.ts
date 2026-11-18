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

export function validarClave(clave: string, correo?: string): string | null {
  if (clave.length < 10 || clave.length > 128) return 'La contraseña debe tener entre 10 y 128 caracteres.';
  if (correo && clave.trim().toLowerCase() === correo.trim().toLowerCase()) return 'La contraseña no puede ser igual al correo.';
  if (new Set(clave).size < 4) return 'La contraseña es demasiado simple: usa más variedad de caracteres.';
  return null;
}

export type DatosRegistro = { invitacion: string; correo: string; clave: string; confirmar: string; aceptoPolitica: boolean; aceptoSigac: boolean };

/** Primer problema del formulario de registro, o null si se puede enviar. */
export function validarRegistro(d: DatosRegistro): string | null {
  if (d.invitacion.replace(/[\s-]/g, '').length < 8) return 'Escribe el código de invitación que te dieron.';
  return validarCorreo(d.correo) ?? validarClave(d.clave, d.correo)
    ?? (d.clave !== d.confirmar ? 'Las contraseñas no coinciden.' : null)
    ?? (!d.aceptoPolitica ? 'Debes aceptar la política de datos y los términos de uso.' : null)
    ?? (!d.aceptoSigac ? 'Debes autorizar la consulta de SIGAC para poder usar Tinotify.' : null);
}

const CODIGOS: Record<string, string> = {
  correo_no_valido: 'Escribe un correo válido.',
  clave_longitud: 'La contraseña debe tener entre 10 y 128 caracteres.',
  clave_muy_simple: 'La contraseña es demasiado simple: usa más variedad de caracteres.',
  clave_igual_al_correo: 'La contraseña no puede ser igual al correo.',
  consentimiento_no_valido: 'Esta versión de la aplicación no está al día con los términos. Actualiza la aplicación.',
};

/** Mensaje claro para un error de las rutas /auth; null si no hay uno específico (se usa el genérico). */
export function mensajeDeAuth(estado: number | null, detalle?: string): string | null {
  if (detalle) {
    const codigo = detalle.startsWith('datos_no_validos:') ? detalle.slice('datos_no_validos:'.length) : detalle;
    if (CODIGOS[codigo]) return CODIGOS[codigo];
  }
  switch (estado) {
    case 400: return 'No se pudo crear la cuenta. Revisa el código de invitación y que el correo no esté ya registrado.';
    case 401: return 'Correo o contraseña incorrectos.';
    case 429: return 'Demasiados intentos o cuenta bloqueada por unos minutos. Espera e inténtalo de nuevo.';
    default: return null;
  }
}
