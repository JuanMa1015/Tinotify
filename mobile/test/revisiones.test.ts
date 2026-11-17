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
