"""
Backfill de una sola vez: convierte los CSV crudos del scraper viejo/manual
(en ~/Downloads) al formato estandar de data/raw/YYYY-MM-DD_SLOT.csv, para
poder ingestarlos con ingest_run.py como si fueran corridas reales.

Problemas que corrige de los CSV originales:
  - En varios de estos archivos la columna "precio" no es el precio real
    sino un valor tipo precio-por-ml (ej. fleje=3749, "precio"=5.16). Se
    detecto comparando contra la formula real de Rappi (precio =
    fleje * (1 - descuento), confirmada contra la API en vivo). Por eso
    esta importacion IGNORA la columna "precio" cruda y siempre recalcula
    precio = fleje * (1 - pct/100) a partir del descuento real (columna
    "dinamica" tipo "35% OFF", o "descuento" numerico cuando no hay
    columna "dinamica").
  - Los formatos con columna "producto" (en vez de "descripcion") tienen
    ademas una columna "descuento" con un valor constante de relleno
    (siempre 100, no es un porcentaje real) - para esos se usa unicamente
    "dinamica".
  - Filas basura de UI mal capturadas ("Agregar", "Patrocinado", "Pronto
    de vuelta") y packs/combos/sixpacks se excluyen.
  - Regla ya documentada en el dashboard original: "100% OFF" es un
    placeholder de Rappi para "sin dinamica activa", no un descuento real
    (nunca hay cerveza gratis) -> se trata como 0%.
  - marca viene vacia ("-") en la mayoria de estos archivos: se infiere
    por nombre de producto (mismo patron que scraper/scrape.py).

No se corre solo (no es parte del pipeline de CI), se corre a mano una
sola vez para cargar el historico pre-existente:
    python3 scripts/import_legacy_csv.py
"""
import csv
import re
from pathlib import Path

DOWNLOADS = Path.home() / "Downloads"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
ZONA = "Nunez"

# (nombre de archivo en Downloads, fecha, slot) - se omiten los duplicados
# confirmados (rappi_cervezas_12.csv/13.csv == 20260813) y el archivo
# vacio (20260811 _120000.csv, 1 sola linea de encabezado).
FILES = [
    ("rappi_cervezas_20260805_092325.csv", "2026-08-05", "AM"),
    ("rappi_cervezas_20260806_112259.csv", "2026-08-06", "AM"),
    ("rappi_cervezas_20260809_133632.csv", "2026-08-09", "AM"),
    ("rappi_cervezas_20260810 _120000.csv", "2026-08-10", "AM"),
    ("rappi_cervezas_20260811_12000.csv", "2026-08-11", "AM"),
    ("rappi_cervezas_20260812 _120000.csv", "2026-08-12", "AM"),
    ("rappi_cervezas_20260813 _120000.csv", "2026-08-13", "AM"),
]

JUNK_NAMES = {"agregar", "patrocinado", "pronto de vuelta", "combo", "-", ""}
PACK_NAME_RE = re.compile(r"^\s*\d+\s*x\s+|\bpack\b|\bcombo\b|sixpack|six\s*pack", re.I)
CALIBRE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|cc|l)\b", re.I)
DINAMICA_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

NAME_BRAND_PATTERNS = [
    ("Salta Cautiva", r"salta\s+cautiva"), ("Quilmes", r"quilmes"),
    ("Stella Artois", r"stella\s*artois"), ("Budweiser", r"budweiser"),
    ("Corona", r"corona"), ("Michelob Ultra", r"michelob"),
    ("Patagonia", r"patagonia"), ("Andes Origen", r"andes\s*origen"),
    ("Andes", r"andes"), ("Brahma", r"brahma"), ("Heineken", r"heineken"),
    ("Amstel", r"amstel"), ("Schneider", r"schneider"), ("Imperial", r"imperial"),
    ("Salta", r"\bsalta\b"), ("Kunstmann", r"kunstmann"), ("Antares", r"antares"),
    ("Pampa", r"pampa"), ("Rabieta", r"rabieta"), ("Estrella Galicia", r"estrella\s*galicia"),
    ("Estrella Damm", r"estrella\s*damm"), ("Grolsch", r"grolsch"),
    ("Guinness", r"guinness|guinnes"), ("Bitburger", r"bitburger"),
    ("Kostritzer", r"k[oö]stritzer"), ("Warsteiner", r"warsteiner"),
    ("Peroni", r"peroni"), ("Miller", r"miller"), ("Blue Moon", r"blue\s*moon"),
    ("Asahi", r"asahi"), ("1890", r"\b1890\b"), ("Temple", r"\btemple\b"),
    ("Goose Island", r"goose\s*island"), ("Starberg", r"starberg"),
    ("Santa Fe", r"santa\s*fe"), ("Sol", r"\bsol\b"), ("Corona 0", r"corona.*cero|corona.*0"),
    ("Quilmes 0", r"quilmes.*0"), ("Stella Artois 0", r"stella.*0"),
]


def marca_de(marca_raw, nombre):
    marca_raw = (marca_raw or "").strip()
    if marca_raw and marca_raw != "-":
        return marca_raw
    lname = nombre.lower()
    for marca, pattern in NAME_BRAND_PATTERNS:
        if re.search(pattern, lname):
            return marca
    return ""


def calibre_de(calibre_raw, nombre):
    calibre_raw = (calibre_raw or "").strip()
    if calibre_raw and calibre_raw != "-":
        return calibre_raw
    m = CALIBRE_RE.search(nombre)
    return m.group(0) if m else "-"


def pct_descuento(dinamica_raw, descuento_raw, tiene_columna_dinamica):
    """Devuelve el % de descuento real (0-100), o None si la fila es un pack
    ("dinamica" == 'Pack') o no se puede determinar."""
    if tiene_columna_dinamica:
        d = (dinamica_raw or "").strip()
        if d.lower() == "pack":
            return None
        if d in ("-", ""):
            return 0.0
        m = DINAMICA_PCT_RE.search(d)
        if m:
            pct = float(m.group(1).replace(",", "."))
            # Regla del dashboard original: Rappi usa "100% OFF" como
            # placeholder de "sin dinamica activa", no como descuento real
            # (nunca vende cerveza gratis). 100% OFF = 0%.
            return 0.0 if pct >= 100 else pct
        return None
    # sin columna "dinamica": la columna "descuento" es el numero real
    try:
        return float(descuento_raw)
    except (TypeError, ValueError):
        return None


def es_junk_o_pack(nombre):
    if nombre.strip().lower() in JUNK_NAMES:
        return True
    return bool(PACK_NAME_RE.search(nombre))


def procesar_archivo(path):
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = reader.fieldnames or []
        tiene_dinamica = "dinamica" in fieldnames
        usa_producto = "producto" in fieldnames and "descripcion" in fieldnames
        rows = list(reader)

    out_rows = []
    saltadas = 0
    for r in rows:
        nombre = (r.get("producto") if usa_producto else r.get("descripcion")) or ""
        nombre = nombre.strip()
        if not nombre or es_junk_o_pack(nombre):
            saltadas += 1
            continue

        try:
            fleje = float(r.get("fleje") or 0)
        except ValueError:
            saltadas += 1
            continue
        if not fleje:
            saltadas += 1
            continue

        pct = pct_descuento(r.get("dinamica"), r.get("descuento"), tiene_dinamica)
        if pct is None:
            saltadas += 1
            continue

        precio = round(fleje * (1 - pct / 100), 2)
        marca = marca_de(r.get("marca"), nombre)
        if not marca:
            saltadas += 1
            continue
        calibre = calibre_de(r.get("calibre"), nombre)

        out_rows.append({
            "zona": ZONA, "marca": marca, "descripcion": nombre,
            "calibre": calibre, "fleje": fleje, "precio": precio,
            "descuento": int(round(pct)),
        })

    return out_rows, saltadas, len(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, fecha, slot in FILES:
        src = DOWNLOADS / filename
        if not src.exists():
            print(f"[AVISO] no encontre {src}, salteo")
            continue
        out_rows, saltadas, total = procesar_archivo(src)
        if not out_rows:
            print(f"[AVISO] {filename}: 0 filas utiles, salteo")
            continue

        dest = OUT_DIR / f"{fecha}_{slot}.csv"
        with dest.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["zona", "marca", "descripcion", "calibre", "fleje", "precio", "descuento"], delimiter=";")
            w.writeheader()
            w.writerows(out_rows)

        print(f"[OK] {filename} -> {dest.name}: {len(out_rows)}/{total} filas "
              f"({saltadas} descartadas: junk/pack/sin marca/sin descuento valido)")


if __name__ == "__main__":
    main()
