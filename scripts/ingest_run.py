"""
Mergea un CSV crudo de una corrida del scraper (data/raw/YYYY-MM-DD.csv)
dentro de data/history.json. Se corre despues de cada scrapeo (1 vez por
dia; el historico previo a AM/PM se migro con scripts/migrate_am_pm.py).

Nunca revienta por una fila individual mala: la loguea en
data/logs/ingest_warnings.log y sigue con las demas (requisito de manejo
de errores del pipeline).

Uso:
    python3 scripts/ingest_run.py --csv data/raw/2026-08-20.csv --date 2026-08-20
"""

import argparse
import csv as csvmod
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CATALOG_PATH,
    HISTORY_PATH,
    bucket_calibre,
    catalog_key,
    load_json,
    log_warning,
    save_json,
    slugify,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"No existe {csv_path}")

    catalog_list = load_json(CATALOG_PATH, [])
    catalog = {catalog_key(c["marca"], c["sku"]): c for c in catalog_list}

    history = load_json(
        HISTORY_PATH,
        {"meta": {"tienda": "Nunez", "plataforma": "Rappi Turbo"}, "dates": [], "pivot": []},
    )
    pivot_by_key = {catalog_key(p["marca"], p["sku"]): p for p in history["pivot"]}

    date_key = args.date

    errores = 0
    nuevos = 0
    ok = 0
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csvmod.DictReader(f, delimiter=";")
        for row in reader:
            try:
                marca = (row.get("marca") or "").strip()
                descripcion = (row.get("descripcion") or "").strip()
                precio_raw = row.get("precio")
                if not marca or not descripcion or not precio_raw:
                    raise ValueError("fila sin marca/descripcion/precio")

                key = catalog_key(marca, descripcion)
                cat = catalog.get(key)
                if cat is None:
                    cat = {
                        "id": slugify(marca, descripcion),
                        "marca": marca,
                        "sku": descripcion,
                        "calibre": bucket_calibre(row.get("calibre")),
                        "grupo": "Sin clasificar",
                        "segmento": "Sin clasificar",
                    }
                    catalog[key] = cat
                    log_warning(
                        f"{csv_path.name}: SKU nuevo sin catalogo -> '{marca} | {descripcion}' "
                        "(agregado como 'Sin clasificar', revisar data/catalog.json)",
                        log_file="ingest_warnings.log",
                    )
                    nuevos += 1

                entry = pivot_by_key.get(key)
                if entry is None:
                    entry = {
                        "id": cat["id"],
                        "marca": cat["marca"],
                        "sku": cat["sku"],
                        "calibre": cat["calibre"],
                        "grupo": cat["grupo"],
                        "segmento": cat["segmento"],
                        "dates": {},
                    }
                    pivot_by_key[key] = entry

                precio = float(precio_raw)
                fleje = float(row.get("fleje") or precio)
                dinamica = round(max(1 - precio / fleje, 0.0), 4) if fleje else 0.0
                entry["dates"][date_key] = {
                    "fleje": fleje,
                    "ptc": precio,
                    "dinamica": dinamica,
                }
                ok += 1
            except Exception as e:  # noqa: BLE001 - una fila mala no debe tumbar la corrida
                errores += 1
                log_warning(
                    f"{csv_path.name}: fila descartada ({e}): {row}",
                    log_file="ingest_warnings.log",
                )

    pivot = list(pivot_by_key.values())
    dates = sorted({d for p in pivot for d in p["dates"]})

    history["pivot"] = pivot
    history["dates"] = dates
    history["meta"]["ultima_corrida"] = datetime.now(timezone.utc).isoformat()
    history["meta"]["sku_count"] = len(pivot)

    save_json(HISTORY_PATH, history)
    save_json(CATALOG_PATH, list(catalog.values()))

    print(f"[OK] {date_key}: {ok} filas ok, {nuevos} SKUs nuevos, {errores} filas con error")
    if errores:
        print("     ver data/logs/ingest_warnings.log")


if __name__ == "__main__":
    main()
