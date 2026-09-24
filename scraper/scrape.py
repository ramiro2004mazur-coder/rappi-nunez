"""
Scraper de precios de cerveza en la tienda de Rappi Turbo de Monroe (Nunez),
store_id 166964 ("Belgrano 1", Monroe 1616).

Por que con navegador y no con requests puro: la pagina de cada subcategoria
(ej. "Cervezas Rubias") solo trae ~24 productos en la carga inicial (SSR via
__NEXT_DATA__), aunque la subcategoria tenga muchos mas. El resto se carga
haciendo click en "Ver mas", que dispara un POST a un endpoint interno de
Rappi (dynamic/context/content) que exige un "device id" generado por el
propio navegador - no se puede replicar de forma simple ni confiable solo
con HTTP. Por eso este scraper usa Playwright, entra a cada subcategoria y
clickea "Ver mas" hasta agotarla, capturando las respuestas de red reales
para no perderse ningun SKU (misma tecnica ya validada en el scraper de
frio de rappi-turbo-frio).

No hace falta login: la pagina de categoria/subcategoria es SSR publica.
El campo que necesitamos ya viene resuelto en el JSON de cada producto:
  real_price -> fleje (precio de lista, tachado)
  price      -> precio real / PTC (precio con descuento aplicado)
  discount   -> dinamica, como fraccion 0-1 (0.3 = 30% OFF)

Se excluyen packs/sixpacks/combos via attributes.pack_size (solo se toma
"x1"); si ese atributo faltara, se aplica una regla de respaldo por nombre.

Si un producto individual falla al parsearse, se loguea y se sigue (no
corta la corrida). Si la tienda entera no devuelve productos, se sale con
codigo de error (eso si debe frenar la corrida de CI).

Corre 1 vez por dia (10:15 ART). Antes corria 2 veces (AM/PM) para ver
variacion intradia, pero se confirmo que la dinamica no cambia segun la
hora del dia, asi que se simplifico a una sola lectura.

Uso:
    python scraper/scrape.py
    python scraper/scrape.py --fecha 2026-08-20 --out-dir ../data/raw
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

BASE = "https://www.rappi.com.ar"
STORE_ID = 166964          # Belgrano 1 / Monroe 1616 ("Nunez")
ZONA = "Nunez"
CATEGORY_SLUG = "cervezas"
MAX_VER_MAS_CLICKS = 25     # tope de seguridad por subcategoria
REQUEST_DELAY = 1.2         # pausa entre acciones, para no forzar el sitio
MAX_PASADAS = 3             # pasadas de scrapeo (contexto nuevo cada una), se acumulan productos
OBJETIVO_COBERTURA = 0.97   # se corta de reintentar al llegar a este % del maximo reciente
MIN_COBERTURA = 0.80        # por debajo de esto la corrida FALLA (no se publica un corte parcial)
# Contextos de las respuestas dynamic/context/content que traen cerveza. "store_home"
# son carruseles de la home (casi no hay cerveza): se excluye a proposito.
CAPTURE_CONTEXTS = ("aisle_detail", "sub_aisles")
CONTEXT_RE = re.compile(r'"context"\s*:\s*"(\w+)"')
TZ = ZoneInfo("America/Argentina/Buenos_Aires")

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
CSV_FIELDS = ["zona", "marca", "descripcion", "calibre", "fleje", "precio", "descuento"]

PACK_NAME_RE = re.compile(r"^\s*\d+\s*x\s+|pack|combo|sixpack|six\s*pack", re.I)
CALIBRE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|cc|l)\b", re.I)

# Respaldo para productos sin "trademark" en el JSON de Rappi (ej. "Corona
# Cerveza 0.0", "Asahi Cerveza Dry"): se detecta la marca por el nombre.
# Orden importa: patrones mas especificos primero.
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
    ("Santa Fe", r"santa\s*fe"), ("Sol", r"\bsol\b"),
    ("Stones", r"\bstones\b"), ("Estrella del Sur", r"estrella\s*del\s*sur"),
]


def marca_de(product):
    tm = (product.get("trademark") or "").strip()
    if tm:
        return tm
    nombre = (product.get("name") or "").lower()
    for marca, pattern in NAME_BRAND_PATTERNS:
        if re.search(pattern, nombre):
            return marca
    return ""


def slugify(text):
    text = text.lower()
    for a, b in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}.items():
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def es_pack(product, attrs):
    pack_size = (attrs.get("pack_size") or "").strip().lower()
    if pack_size:
        return pack_size not in ("x1", "1", "")
    return bool(PACK_NAME_RE.search(product.get("name") or ""))


def calibre_de(product, attrs):
    vol = attrs.get("volume") or product.get("presentation") or product.get("name") or ""
    m = CALIBRE_RE.search(str(vol))
    if not m:
        return "-"
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    ml = num * 1000 if unit == "l" else num
    return f"{int(round(ml))} ml"


def producto_a_fila(p):
    attrs = p.get("attributes") or {}
    if es_pack(p, attrs):
        return None

    marca = marca_de(p)
    descripcion = (p.get("name") or "").strip()
    fleje = p.get("real_price")
    precio = p.get("price")
    if not descripcion or precio is None:
        raise ValueError(f"producto sin nombre/precio (product_id={p.get('product_id')})")
    if fleje is None:
        fleje = precio
    discount = p.get("discount")
    if discount is None:
        discount = round(max(1 - (precio / fleje if fleje else 1), 0.0), 4)
    if discount >= 1.0:
        # Regla del dashboard: "100% OFF" es placeholder de Rappi para "sin
        # dinamica activa", no un descuento real (nunca hay cerveza gratis).
        discount = 0.0
        precio = fleje
    descuento = int(round(discount * 100))

    return {
        "zona": ZONA,
        "marca": marca,
        "descripcion": descripcion,
        "calibre": calibre_de(p, attrs),
        "fleje": fleje,
        "precio": precio,
        "descuento": descuento,
    }


def _make_handler(bucket):
    def handle_response(response):
        if "dynamic/context/content" not in response.url:
            return
        try:
            m = CONTEXT_RE.search(response.request.post_data or "")
            if not m or m.group(1) not in CAPTURE_CONTEXTS:
                return
            data = response.json()
            for comp in data.get("data", {}).get("components", []):
                for p in comp.get("resource", {}).get("products", []):
                    bucket[p["product_id"]] = p
        except Exception:
            pass
    return handle_response


def expandir_ver_mas(page):
    """Clickea 'Ver mas' hasta agotar la lista. Tolera 1 click sin crecimiento
    (respuesta lenta) antes de darse por vencido. Devuelve la cantidad de clicks."""
    clicks = fallos = 0
    for _ in range(MAX_VER_MAS_CLICKS):
        antes = page.locator('a[href^="/p/"]').count()
        clicked = page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button, a'))
                    .find(el => /ver\\s*m[a\u00e1]s/i.test(el.textContent || ''));
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        if not clicked:
            break
        clicks += 1
        crecio = False
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator('a[href^="/p/"]').count() > antes:
                crecio = True
                break
        if crecio:
            fallos = 0
        else:
            fallos += 1
            if fallos >= 2:
                break
    return clicks


def scrape_store(page, store_id, category_slug=CATEGORY_SLUG, all_products=None):
    """Una pasada completa. Acumula en all_products (compartido entre pasadas)."""
    all_products = {} if all_products is None else all_products
    url = f"{BASE}/tiendas/{store_id}-turbo-express/{category_slug}"
    handler = _make_handler(all_products)
    page.on("response", handler)
    try:
        page.goto(url, wait_until="networkidle", timeout=45000)

        next_data = page.evaluate(
            "() => JSON.parse(document.getElementById('__NEXT_DATA__').textContent)"
        )
        pageProps = next_data["props"]["pageProps"]
        fallback = pageProps.get("fallback", {})
        fbkey = next(iter(fallback), None)

        subcats = []
        if fbkey:
            sar = fallback[fbkey].get("sub_aisles_response", {}).get("data", {})
            for h in sar.get("headers", []):
                for c in h.get("resource", {}).get("categories", []):
                    subcats.append({"id": c["id"], "name": c["name"]})
            for comp in sar.get("components", []):
                for p in comp.get("resource", {}).get("products", []):
                    all_products[p["product_id"]] = p

        print(f"[store {store_id}] {len(subcats)} subcategorias: {', '.join(s['name'] for s in subcats)}")

        # La pagina principal de la categoria tambien pagina con "Ver mas"
        # (contexto sub_aisles): ahi carga la mayor parte del catalogo.
        before = len(all_products)
        clicks = expandir_ver_mas(page)
        print(f"    - (categoria completa): +{len(all_products) - before} productos ({clicks} click(s) en 'Ver mas')")

        for sub in subcats:
            sub_url = f"{url}/{slugify(sub['name'])}"
            before = len(all_products)
            try:
                page.goto(sub_url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"    [!] no se pudo cargar subcategoria '{sub['name']}': {e}")
                continue

            try:
                sub_next_data = page.evaluate(
                    "() => JSON.parse(document.getElementById('__NEXT_DATA__').textContent)"
                )
                sub_fallback = sub_next_data["props"]["pageProps"].get("fallback", {})
                sub_fbkey = next(iter(sub_fallback), None)
                if sub_fbkey:
                    ad = sub_fallback[sub_fbkey].get("aisle_detail_response", {}).get("data", {})
                    for comp in ad.get("components", []):
                        for p in comp.get("resource", {}).get("products", []):
                            all_products[p["product_id"]] = p
            except Exception:
                pass

            clicks = expandir_ver_mas(page)
            print(f"    - {sub['name']}: +{len(all_products) - before} productos ({clicks} click(s) en 'Ver mas')")
            time.sleep(REQUEST_DELAY)
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
    return list(all_products.values())


def contar_cervezas(products):
    n = 0
    for p_ in products:
        try:
            if producto_a_fila(p_) is not None:
                n += 1
        except Exception:
            pass
    return n


def referencia_previa(out_dir, fecha):
    """(max de filas, nombres) entre los ultimos 7 CSV previos: sirve de vara de
    cobertura. Se usa el maximo (no el ultimo) para que un dia parcial no baje la vara."""
    mejor = (0, set())
    for f in sorted(Path(out_dir).glob("????-??-??.csv"))[-8:]:
        if f.stem >= fecha:
            continue
        try:
            with f.open(encoding="utf-8-sig", newline="") as fh:
                nombres = {r["descripcion"].strip().lower() for r in csv.DictReader(fh, delimiter=";")}
        except Exception:
            continue
        if len(nombres) > mejor[0]:
            mejor = (len(nombres), nombres)
    return mejor


def guardar_csv(rows, out_dir, fecha):
    out_dir.mkdir(parents=True, exist_ok=True)
    destino = out_dir / f"{fecha}.csv"
    with destino.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return destino


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--fecha", default=None, help="YYYY-MM-DD (default: hoy en ART)")
    ap.add_argument("--store-id", type=int, default=STORE_ID)
    ap.add_argument("--min-cobertura", type=float, default=MIN_COBERTURA,
                    help="fraccion minima de SKUs vs el maximo reciente; 0 desactiva el chequeo")
    args = ap.parse_args()

    ahora = datetime.now(TZ)
    fecha = args.fecha or ahora.strftime("%Y-%m-%d")

    print("=" * 55)
    print("  Scraper Rappi Turbo - Nunez (Monroe)")
    print(f"  Store: {args.store_id}  |  Zona: {ZONA}  |  Fecha: {fecha}")
    print("=" * 55)

    errores_run = []
    ref_n, ref_names = referencia_previa(args.out_dir, fecha)
    all_products = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for pasada in range(1, MAX_PASADAS + 1):
            context = browser.new_context(locale="es-AR")  # contexto nuevo = device id nuevo
            page = context.new_page()
            try:
                scrape_store(page, args.store_id, CATEGORY_SLUG, all_products)
            except Exception as e:
                print(f"[!] Error en la pasada {pasada}/{MAX_PASADAS}: {e}")
            finally:
                context.close()
            n = contar_cervezas(all_products.values())
            print(f"[pasada {pasada}/{MAX_PASADAS}] {n} cervezas acumuladas "
                  f"(referencia: {ref_n or 'n/d'})")
            if n and (not ref_n or n >= ref_n * OBJETIVO_COBERTURA):
                break
            time.sleep(4 * pasada)
        browser.close()

    products = list(all_products.values())
    if not products:
        print("\n[ERROR] No se obtuvieron productos. Revisa el store_id o la conectividad.")
        sys.exit(1)

    rows = []
    for p_ in products:
        try:
            row = producto_a_fila(p_)
            if row is not None:  # None = era un pack/sixpack/combo, se excluye
                rows.append(row)
        except Exception as e:
            errores_run.append(f"product_id={p_.get('product_id')} descartado: {e}")

    if not rows:
        print("\n[ERROR] Ningun producto se pudo parsear.")
        sys.exit(1)

    destino = guardar_csv(rows, args.out_dir, fecha)
    if ref_n and len(rows) < ref_n * args.min_cobertura:
        hoy = {r["descripcion"].strip().lower() for r in rows}
        faltan = sorted(ref_names - hoy)
        print(f"\n[ERROR] Cobertura insuficiente: {len(rows)} de {ref_n} SKUs de referencia "
              f"({len(rows) / ref_n:.0%} < {args.min_cobertura:.0%}). No se publica el corte.")
        print(f"        Faltan {len(faltan)}: {', '.join(faltan[:25])}{' ...' if len(faltan) > 25 else ''}")
        sys.exit(2)
    con_desc = sum(1 for r in rows if r["descuento"] and r["descuento"] > 0)

    print(f"\n[OK] {len(rows)} cervezas guardadas ({con_desc} con descuento, "
          f"{len(products) - len(rows) - len(errores_run)} packs/combos excluidos)")
    print(f"     -> {destino}")
    if errores_run:
        print(f"\n[WARN] {len(errores_run)} productos descartados (no rompieron la corrida):")
        for e in errores_run:
            print("   -", e)

    gha_out = os.environ.get("GITHUB_OUTPUT")
    if gha_out:
        with open(gha_out, "a", encoding="utf-8") as f:
            f.write(f"csv_path={destino.resolve()}\n")
            f.write(f"fecha={fecha}\n")


if __name__ == "__main__":
    main()
