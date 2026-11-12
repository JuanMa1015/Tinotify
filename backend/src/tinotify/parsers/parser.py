from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlsplit, parse_qs

@dataclass(frozen=True)
class Anexo:
    descripcion: str
    archivo: str
    referencia: str

@dataclass(frozen=True)
class Actuacion:
    etapa: str
    origen: str
    destino: str
    fecha: datetime
    remitente: str
    descripcion: str
    huella: str
    anexos: tuple[Anexo, ...] = ()

def clean(node: Tag) -> str:
    return node.get_text(' ', strip=True)

def parse_actuaciones(html: str, caso_id: str) -> list[Actuacion]:
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    # Each record starts with a row containing an HR, followed by 3 TR rows.
    for sep in soup.select('tr'):
        if not sep.find('hr'):
            continue
        rows = []
        cursor = sep.find_next_sibling('tr')
        while cursor is not None and len(rows) < 3:
            if cursor.find('hr'):
                break
            rows.append(cursor)
            cursor = cursor.find_next_sibling('tr')
        if len(rows) != 3:
            continue
        cells = [r.find_all('td', recursive=False) for r in rows]
        if any(len(c) != 2 for c in cells):
            continue
        etapa, sentido = map(clean, cells[0])
        if '-->' not in sentido:
            continue
        origen, destino = [p.strip().upper() for p in sentido.split('-->', 1)]
        try:
            fecha = datetime.strptime(clean(cells[1][0]), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        remitente = clean(cells[1][1])
        if not re.match(r'^Actuaci[oó]n\s*:', clean(cells[2][0]), re.I):
            continue
        descripcion = cells[2][1].get_text('\n', strip=True)
        descripcion = re.sub(r'\n{3,}', '\n\n', descripcion).strip()
        signature = '\x1f'.join((caso_id, fecha.isoformat(), origen, destino, remitente, descripcion))
        anexos = []
        # Optional annex row immediately after the description row.
        if cursor is not None:
            annex_cells = cursor.find_all('td', recursive=False)
            if len(annex_cells) == 2 and re.match(r'^Anexos\s*:', clean(annex_cells[0]), re.I):
                annex_table = annex_cells[1].find('table', id='tablaAnexos')
                if annex_table:
                    for annex_row in annex_table.find_all('tr'):
                        parts = annex_row.find_all('td', recursive=False)
                        if len(parts) != 2:
                            continue
                        link = parts[1].find('a', href=True)
                        if not link:
                            continue
                        href = link['href'].strip()
                        # Keep only an internal relative reference. Never request the URL here.
                        parsed = urlsplit(href)
                        if parsed.scheme or parsed.netloc or not parsed.path.endswith('general.descargarAnexo.con'):
                            continue
                        anexos.append(Anexo(clean(parts[0]), clean(link), href))
        result.append(Actuacion(etapa, origen, destino, fecha, remitente, descripcion, sha256(signature.encode()).hexdigest(), tuple(anexos)))
    return result
