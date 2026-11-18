import assert from 'node:assert/strict';
import test from 'node:test';
import { esTokenDeUsuario, mensajeDeAuth, validarClave, validarCorreo, validarRegistro } from '../src/cuentas.ts';

const BUENO = { invitacion: 'ABCD-EFGH-JKMN-PQRS', correo: 'persona@ejemplo.com', clave: 'una-clave-ficticia-1', confirmar: 'una-clave-ficticia-1', aceptoPolitica: true, aceptoSigac: true };

test('el correo se valida como en el servidor', () => {
  assert.equal(validarCorreo(' Persona@Ejemplo.COM '), null);
  for (const malo of ['', 'sin-arroba', 'a@b', 'a@@b.com', 'a..b@c.com', 'a b@c.com']) assert.notEqual(validarCorreo(malo), null, malo);
});

test('la contraseña exige longitud, variedad y no parecerse al correo', () => {
  assert.equal(validarClave('una-clave-ficticia-1'), null);
  assert.match(validarClave('corta')!, /entre 10 y 128/);
  assert.match(validarClave('x'.repeat(200))!, /entre 10 y 128/);
  assert.match(validarClave('aaaaaaaaaaaa')!, /simple/);
  assert.match(validarClave('persona@ejemplo.com', 'Persona@Ejemplo.com')!, /igual al correo/);
});

test('el registro valida en orden y exige las dos casillas', () => {
  assert.equal(validarRegistro(BUENO), null);
  assert.match(validarRegistro({ ...BUENO, invitacion: 'abc' })!, /invitación/);
  assert.match(validarRegistro({ ...BUENO, correo: 'mal' })!, /correo/);
  assert.match(validarRegistro({ ...BUENO, confirmar: 'otra-clave-ficticia' })!, /no coinciden/);
  assert.match(validarRegistro({ ...BUENO, aceptoPolitica: false })!, /política/);
  assert.match(validarRegistro({ ...BUENO, aceptoSigac: false })!, /SIGAC/);
});

test('los errores del servidor se traducen a mensajes claros', () => {
  assert.match(mensajeDeAuth(422, 'datos_no_validos:clave_longitud')!, /entre 10 y 128/);
  assert.match(mensajeDeAuth(422, 'consentimiento_no_valido')!, /Actualiza/);
  assert.match(mensajeDeAuth(400)!, /invitación/);
  assert.equal(mensajeDeAuth(401), 'Correo o contraseña incorrectos.');
  assert.match(mensajeDeAuth(429)!, /Espera/);
  assert.equal(mensajeDeAuth(500), null);
});

test('un token tn_ es de usuario y el resto del propietario', () => {
  assert.equal(esTokenDeUsuario('tn_abc'), true);
  assert.equal(esTokenDeUsuario('codigo-del-propietario'), false);
});
