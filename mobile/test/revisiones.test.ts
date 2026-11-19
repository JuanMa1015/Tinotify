import assert from 'node:assert/strict';
import test from 'node:test';
import { proximaRevision, resumenDeEstado } from '../src/revisiones.ts';
import { urlValida } from '../src/config.ts';

test('la próxima revisión respeta 7:30, 12:30 y 18:30 de Bogotá', () => {
  const casos: [string, string, string][] = [
    ['2026-11-17T05:00:00Z', '2026-11-17T12:30:00.000Z', '7:30'],
    ['2026-11-17T12:30:00Z', '2026-11-17T17:30:00.000Z', '12:30'],
    ['2026-11-17T18:00:00Z', '2026-11-17T23:30:00.000Z', '18:30'],
    ['2026-11-17T23:30:00Z', '2026-11-18T12:30:00.000Z', '7:30'],
  ];
  for (const [ahora, esperada, etiqueta] of casos) {
    const r = proximaRevision(new Date(ahora));
    assert.equal(r.fecha.toISOString(), esperada);
    assert.equal(r.etiqueta, etiqueta);
  }
});

test('el resumen traduce cada resultado y avisa cuando hace falta atención', () => {
  const base = { credenciales_guardadas: true, expedientes_en_estado: 15, avisos_pendientes: 0 };
  const con = (resultado: string) => resumenDeEstado({ ...base, ultima_ejecucion: { resultado, inicio: '2026-11-17T17:30:00Z', fin: null } });
  assert.equal(con('ok').titulo, 'Todo al día');
  assert.equal(con('ok').requiereAtencion, false);
  assert.equal(con('error_acceso').titulo, 'Actualiza tu clave');
  assert.equal(con('error_acceso').requiereAtencion, true);
  assert.equal(con('anomalia').requiereAtencion, true);
  assert.equal(resumenDeEstado({ ...base, credenciales_guardadas: false, ultima_ejecucion: null }).requiereAtencion, true);
  assert.equal(resumenDeEstado({ ...base, ultima_ejecucion: null }).requiereAtencion, false);
});

test('la URL del servidor exige HTTPS sin credenciales ni parámetros', () => {
  assert.equal(urlValida('https://tinotify.onrender.com'), 'https://tinotify.onrender.com');
  for (const mala of ['http://x.example', 'https://u:p@x.example', 'https://x.example/?a=1', 'https://x.example/ruta', 'no-es-url']) {
    assert.throws(() => urlValida(mala));
  }
  assert.equal(urlValida('http://localhost:8000', true), 'http://localhost:8000');
  assert.throws(() => urlValida('http://localhost:8000', false));
});

import { duracionTexto, fechaHoraBogota, resumenDeEjecucion } from '../src/revisiones.ts';

test('la fecha se muestra como Hoy, Ayer o día y mes, en hora de Bogotá', () => {
  const ahora = new Date('2026-11-17T20:00:00Z'); // 15:00 en Bogotá
  assert.match(fechaHoraBogota('2026-11-17T17:30:00Z', ahora), /^Hoy, 12:30 p\. m\.$/);
  assert.match(fechaHoraBogota('2026-11-16T12:30:00Z', ahora), /^Ayer, /);
  assert.match(fechaHoraBogota('2026-11-10T12:30:00Z', ahora), /^10 nov/);
  assert.equal(fechaHoraBogota('basura', ahora), '--');
  assert.match(fechaHoraBogota('2026-11-17T04:59:00Z', ahora), /^Ayer, 11:59 p\. m\.$/); // 23:59 del día anterior en Bogotá
});

test('la duración y el resumen de cada revisión', () => {
  assert.equal(duracionTexto('2026-11-17T12:30:00Z', '2026-11-17T12:33:05Z'), '3 min 5 s');
  assert.equal(duracionTexto('2026-11-17T12:30:00Z', '2026-11-17T12:30:20Z'), '20 s');
  assert.equal(duracionTexto('2026-11-17T12:30:00Z', null), null);
  const r = resumenDeEjecucion({ inicio: 'x', fin: null, resultado: 'ok', expedientes: 15, novedades: 2, codigo: null });
  assert.deepEqual([r.titulo, r.detalle, r.ok], ['Todo al día', '15 expedientes revisados · 2 actuaciones nuevas', true]);
  assert.equal(resumenDeEjecucion({ inicio: 'x', fin: null, resultado: 'error_acceso', expedientes: null, novedades: null, codigo: 'x' }).ok, false);
  assert.equal(resumenDeEjecucion({ inicio: 'x', fin: null, resultado: 'en_curso', expedientes: null, novedades: null, codigo: null }).titulo, 'Revisión en curso');
});

import { canalesDeAviso } from '../src/revisiones.ts';

test('los canales del aviso dicen por dónde salió y si falló', () => {
  assert.deepEqual(canalesDeAviso(null), []);
  assert.deepEqual(canalesDeAviso({ push: 'enviado', correo: 'enviado' }).map(c => [c.texto, c.ok]), [['Notificación enviada', true], ['Correo enviado', true]]);
  const fallo = canalesDeAviso({ push: 'fallido', correo: 'fallido' });
  assert.deepEqual(fallo.map(c => c.ok), [false, false]);
  assert.equal(canalesDeAviso({ push: null, correo: null })[0].texto, 'Correo en espera del próximo envío');
  assert.equal(canalesDeAviso({ push: 'sin_dispositivos', correo: 'desactivado' })[0].texto, 'Notificación: sin teléfonos registrados');
});

import { parsearDescripcion, tipoDireccion } from '../src/revisiones.ts';

test('las actuaciones con formato de formulario se separan en etiqueta y valor', () => {
  const crudo = 'TINOTIFY_FILAS_V1:' + JSON.stringify({ filas: [['Aprobada por', 'PERSONA FICTICIA'], ['Hechos', 'PRIMERO. Uno.\nSEGUNDO. Dos.']] });
  const d = parsearDescripcion(crudo);
  assert.equal(d.tipo, 'filas');
  if (d.tipo === 'filas') {
    assert.deepEqual(d.filas.map(f => f.etiqueta), ['Aprobada por', 'Hechos']);
    assert.equal(d.filas[1].valor, 'PRIMERO. Uno.\nSEGUNDO. Dos.');
  }
  for (const raro of ['texto normal', 'TINOTIFY_FILAS_V1:{no es json', 'TINOTIFY_FILAS_V1:{"filas":"x"}', 'TINOTIFY_FILAS_V1:{"filas":[["solo uno"]]}', 'TINOTIFY_FILAS_V1:{"filas":[]}']) {
    assert.deepEqual(parsearDescripcion(raro), { tipo: 'texto', texto: raro });
  }
});

test('la dirección de la actuación se reconoce sin importar mayúsculas', () => {
  assert.equal(tipoDireccion('ESTUDIANTE', 'ASESOR'), 'estudiante_asesor');
  assert.equal(tipoDireccion(' Asesor ', 'estudiante'), 'asesor_estudiante');
  assert.equal(tipoDireccion('X', 'Y'), 'otra');
  assert.equal(tipoDireccion('ASESOR', 'DIRECCIÓN'), 'direccion');
  assert.equal(tipoDireccion('Direccion', 'Asesor'), 'direccion');
});


import { tonoDeEstado } from '../src/revisiones.ts';

test('una revisión que quedó en curso mucho tiempo se muestra como interrumpida y los códigos se explican', () => {
  const base = { credenciales_guardadas: true, expedientes_en_estado: 15, avisos_pendientes: 0 };
  const con = (resultado: string, inicio: string, codigo: string | null = null) => resumenDeEstado({ ...base, ultima_ejecucion: { resultado, inicio, fin: null, codigo } }, new Date('2026-11-18T05:00:00Z'));
  assert.equal(con('en_curso', '2026-11-18T04:55:00Z').titulo, 'Revisión en curso');
  assert.equal(con('en_curso', '2026-11-18T04:55:00Z').requiereAtencion, false);
  assert.equal(con('en_curso', '2026-11-18T04:30:00Z').titulo, 'Revisión interrumpida');
  assert.equal(con('ok', '2026-11-18T04:30:00Z', 'casos_fallidos').titulo, 'Revisión parcial');
  assert.match(con('error_interno', '2026-11-18T04:30:00Z', 'presupuesto_agotado').detalle, /Demasiados accesos/);
  assert.equal(con('error_interno', '2026-11-18T04:30:00Z', 'interrumpida').titulo, 'Revisión interrumpida');
  assert.equal(con('error_interno', '2026-11-18T04:30:00Z').titulo, 'Revisión con problemas');
});

test('el estado del expediente se clasifica para colorearlo', () => {
  assert.equal(tonoDeEstado('En proceso'), 'proceso');
  assert.equal(tonoDeEstado(' EN PROCESO '), 'proceso');
  assert.equal(tonoDeEstado('Terminado'), 'cerrado');
  assert.equal(tonoDeEstado('Archivado'), 'cerrado');
  assert.equal(tonoDeEstado('Reparto'), 'otro');
});


import { agruparPorDia, etiquetaDia } from '../src/revisiones.ts';

test('las novedades se agrupan por día de Bogotá', () => {
  const ahora = new Date('2026-11-18T20:00:00Z');
  assert.equal(etiquetaDia('2026-11-18T17:30:00Z', ahora), 'Hoy');
  assert.equal(etiquetaDia('2026-11-18T04:00:00Z', ahora), 'Ayer'); // 23:00 del 17 en Bogotá
  assert.match(etiquetaDia('2026-11-10T12:30:00Z', ahora), /^10 nov/);
  assert.equal(etiquetaDia('basura', ahora), '--');
  const g = agruparPorDia([{ detectada_en: '2026-11-18T17:30:00Z' }, { detectada_en: '2026-11-18T12:30:00Z' }, { detectada_en: '2026-11-17T12:30:00Z' }], ahora);
  assert.deepEqual(g.map(x => [x.dia, x.items.length]), [['Hoy', 2], ['Ayer', 1]]);
});


import { nombreParaSaludo } from '../src/revisiones.ts';

test('el nombre del saludo se limpia y se acota', () => {
  assert.equal(nombreParaSaludo('  Ana   María  '), 'Ana María');
  assert.equal(nombreParaSaludo(null), '');
  assert.equal(nombreParaSaludo('   '), '');
  assert.equal(nombreParaSaludo('x'.repeat(80)).length, 40);
});


import { primerNombre } from '../src/revisiones.ts';

test('el saludo usa el primer nombre con inicial mayúscula', () => {
  assert.equal(primerNombre('MARIA JOSE PEREZ DIAZ'), 'Maria');
  assert.equal(primerNombre('  ñandú  lópez '), 'Ñandú');
  assert.equal(primerNombre(''), '');
  assert.equal(primerNombre(null), '');
});
