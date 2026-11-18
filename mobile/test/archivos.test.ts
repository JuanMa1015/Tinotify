import assert from 'node:assert/strict';
import test from 'node:test';
import { nombreSeguro } from '../src/archivos.ts';

test('el nombre del anexo se sanea antes de guardarlo', () => {
  assert.equal(nombreSeguro('Informe previo.docx'), 'Informe previo.docx');
  assert.equal(nombreSeguro('WhatsApp Image 2026-11-14 at 9.18.15 AM.jpeg'), 'WhatsApp Image 2026-11-14 at 9.18.15 AM.jpeg');
  assert.ok(!nombreSeguro('../../etc/passwd').includes('/') && !nombreSeguro('..\\..\\x.pdf').includes('\\'));
  assert.ok(!nombreSeguro('a/b\\c:d*e?.pdf').match(/[\/:*?]/));
  assert.equal(nombreSeguro(''), 'anexo');
  assert.equal(nombreSeguro('   '), 'anexo');
  assert.equal(nombreSeguro('.'), 'anexo');
  assert.equal(nombreSeguro('Resolución nº 5.pdf'), 'Resolución nº 5.pdf');
  assert.ok(nombreSeguro('x'.repeat(500) + '.pdf').length <= 100);
});
