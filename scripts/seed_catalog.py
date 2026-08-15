"""
Helper de una sola vez: completa el grupo/segmento de los SKUs que
ingest_run.py dejo como "Sin clasificar" en data/catalog.json, a partir de
una clasificacion por MARCA (no por texto exacto de SKU, que difiere entre
plataformas). Fuentes:

  - marca -> (grupo, segmento) mas frecuente en el catalogo ya curado de
    pedidosya-nunez (mismo universo de cervezas, distinta plataforma).
  - Para marcas que no aparecian ahi: set CMQ_BRANDS ya usado en el
    prototipo rappi-scraper/build_dashboard_data.py (conocimiento publico
    de portfolios AB InBev/CMQ vs el resto).

No se corre solo (no forma parte del workflow de CI): se corre a mano
despues de la primera carga real de SKUs de Rappi, y de nuevo si aparece
una marca nueva que ninguna de las dos fuentes conoce (esas quedan
"Sin clasificar" igual, para revision manual, como ya documenta el README).

Uso:
    python3 scripts/seed_catalog.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CATALOG_PATH, load_json, save_json  # noqa: E402

PEYA_CATALOG = Path(__file__).resolve().parent.parent.parent / "pedidosya-nunez" / "data" / "catalog.json"

# Conocimiento publico de portfolios (rappi-scraper/build_dashboard_data.py) para
# marcas que no existian en el catalogo de PedidosYa.
CMQ_BRANDS_FALLBACK = {
    "Quilmes", "Quilmes 0", "Brahma", "Stella Artois", "Stella Artois 0",
    "Budweiser", "Corona", "Corona 0", "Michelob Ultra", "Patagonia",
    "Andes", "Andes Origen", "1890", "Norte", "Palermo", "Liberty",
}


def marca_map_desde_peya():
    if not PEYA_CATALOG.exists():
        print(f"[AVISO] no encontre {PEYA_CATALOG}, sigo solo con el fallback")
        return {}
    entries = json.loads(PEYA_CATALOG.read_text(encoding="utf-8"))
    por_marca = {}
    for e in entries:
        if e["grupo"] == "Sin clasificar":
            continue  # PedidosYa tampoco la tenia clasificada, no sirve de precedente
        por_marca.setdefault(e["marca"], []).append((e["grupo"], e["segmento"]))
    out = {}
    for marca, pares in por_marca.items():
        (grupo, segmento), _ = Counter(pares).most_common(1)[0]
        out[marca] = (grupo, segmento)
    return out


def main():
    catalog = load_json(CATALOG_PATH, [])
    marca_map = marca_map_desde_peya()

    completados, sin_dato = 0, set()
    for entry in catalog:
        if entry["grupo"] != "Sin clasificar":
            continue
        marca = entry["marca"]
        if marca in marca_map:
            grupo, segmento = marca_map[marca]
        elif marca in CMQ_BRANDS_FALLBACK:
            grupo, segmento = "CMQ", "Sin clasificar"
        elif marca:
            grupo, segmento = "Competencia", "Sin clasificar"
        else:
            sin_dato.add(entry["sku"])
            continue
        entry["grupo"] = grupo
        if entry["segmento"] == "Sin clasificar":
            entry["segmento"] = segmento
        completados += 1

    save_json(CATALOG_PATH, catalog)
    print(f"[OK] {completados} SKUs clasificados por marca en {CATALOG_PATH}")
    if sin_dato:
        print(f"[AVISO] {len(sin_dato)} SKUs sin marca detectada, revisar a mano:")
        for s in sorted(sin_dato):
            print("   -", s)
    segmento_pend = [e["sku"] for e in catalog if e.get("segmento") == "Sin clasificar"]
    if segmento_pend:
        print(f"\n[NOTA] {len(segmento_pend)} SKUs quedaron con grupo ok pero segmento "
              f"'Sin clasificar' (marca nueva sin precedente en PedidosYa) - "
              f"completar segmento a mano en data/catalog.json si te importa esa columna.")


if __name__ == "__main__":
    main()
