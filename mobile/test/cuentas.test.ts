import assert from 'node:assert/strict';
import test from 'node:test';
import { TEXTOS_CODIGO, esTokenDeUsuario, mensajeDeAuth, validarCorreo, validarInvitacion } from '../src/cuentas.ts';

test('el correo se valida como en el servidor', () => {
  assert.equal(validarCorreo(' Persona@Ejemplo.COM '), null);
  for (const malo of ['', 'sin-arroba', 'a@b', 'a@@b.com', 'a..b@c.com', 'a b@c.com']) assert.notEqual(validarCorreo(malo), null, malo);
});

test('la invitación se acepta con o sin guiones y exige longitud', () => {
  assert.equal(validarInvitacion('ABCD-EFGH-JKMN-PQRS'), null);
  assert.equal(validarInvitacion(' abcd efgh jkmn pqrs '), null);
  assert.match(validarInvitacion('abc')!, /invitación/);
});

test('cada respuesta del servidor al pedir un código tiene un texto claro para la persona', () => {
  for (const estado of ['no_registrado', 'limite', 'fallo_envio', 'invitacion_invalida', 'ya_registrado', 'correo_invalido']) {
    assert.ok(TEXTOS_CODIGO[estado] && TEXTOS_CODIGO[estado].length > 20, estado);
  }
  assert.match(TEXTOS_CODIGO.ya_registrado, /Entrar/);
  assert.match(TEXTOS_CODIGO.no_registrado, /mismo con el que creaste/);
});

test('los errores del servidor se traducen a mensajes claros', () => {
  assert.match(mensajeDeAuth(422, 'consentimiento_no_valido')!, /Actualiza/);
  assert.match(mensajeDeAuth(400)!, /código no es válido/);
  assert.match(mensajeDeAuth(401)!, /sesión/);
  assert.match(mensajeDeAuth(429)!, /Espera/);
  assert.equal(mensajeDeAuth(500), null);
});

test('un token tn_ es de usuario y el resto del propietario', () => {
  assert.equal(esTokenDeUsuario('tn_abc'), true);
  assert.equal(esTokenDeUsuario('codigo-del-propietario'), false);
});
