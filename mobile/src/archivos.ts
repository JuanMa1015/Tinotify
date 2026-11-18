// Lógica pura de archivos (sin módulos nativos): nombre seguro para guardar un anexo en el teléfono.

/** Sin rutas, sin caracteres especiales y con un tope de longitud; nunca vacío. */
export function nombreSeguro(nombre: string): string {
  const limpio = nombre.replace(/[^\p{L}\p{N} ._()-]/gu, '_').replace(/\.{2,}/g, '.').trim().slice(0, 100);
  return limpio === '' || limpio === '.' ? 'anexo' : limpio;
}
