"""
Migracion de una sola vez: colapsa las fechas que tienen corrida AM y PM
en data/history.json a una sola lectura diaria (el proyecto paso de 2
corridas/dia a 1, ver README).

Regla para elegir cual corrida se queda (nunca se promedian ni combinan):
  - La que haya scrapeado mas SKUs ese dia.
  - Si empatan en cantidad de SKUs, se queda la PM.
  - La otra se descarta por completo para esa fecha.

Fechas que ya tenian una sola corrida (sin AM/PM, o solo una de las dos)
simplemente se renombran a la fecha pelada.

Uso (se corre una sola vez, no es parte del pipeline):
    python3 scripts/migrate_am_pm.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HISTORY_PATH, load_json, save_json  # noqa: E402

SLOT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_(AM|PM))?$")


def main():
    history = load_json(HISTORY_PATH, None)
    if history is None:
        sys.exit(f"No existe {HISTORY_PATH}")

    pivot = history["pivot"]

    # 1) agrupar los date-keys existentes por fecha base, y contar cuantos
    #    SKUs tiene cada slot (para decidir el ganador por fecha).
    por_fecha = defaultdict(dict)  # {fecha: {slot_o_None: [date_key,...]}}
    for date_key in {d for p in pivot for d in p["dates"]}:
        m = SLOT_RE.match(date_key)
        if not m:
            print(f"[AVISO] date-key con formato inesperado, lo dejo como esta: {date_key}")
            continue
        fecha, slot = m.group(1), m.group(2)
        por_fecha[fecha][slot] = date_key

    conteo_sku = defaultdict(int)  # {date_key: cuantos SKUs tienen ese date_key}
    for p in pivot:
        for date_key in p["dates"]:
            conteo_sku[date_key] += 1

    ganador_por_fecha = {}
    for fecha, slots in por_fecha.items():
        if len(slots) == 1:
            (unico_key,) = slots.values()
            ganador_por_fecha[fecha] = unico_key
            continue
        am_key, pm_key = slots.get("AM"), slots.get("PM")
        n_am, n_pm = conteo_sku.get(am_key, 0), conteo_sku.get(pm_key, 0)
        ganador = pm_key if n_pm >= n_am else am_key
        ganador_por_fecha[fecha] = ganador
        print(f"{fecha}: AM={n_am} SKUs, PM={n_pm} SKUs -> me quedo con "
              f"{'PM' if ganador == pm_key else 'AM'} ({ganador})")

    # 2) reescribir "dates" de cada SKU: solo la fecha pelada, con el valor
    #    del date-key ganador de esa fecha (si ese SKU no estaba en la
    #    corrida ganadora, no se inventa nada: se pierde para esa fecha).
    fechas_vistas = set()
    for p in pivot:
        nuevas_dates = {}
        for fecha, date_key_ganador in ganador_por_fecha.items():
            valor = p["dates"].get(date_key_ganador)
            if valor is not None:
                nuevas_dates[fecha] = valor
                fechas_vistas.add(fecha)
        p["dates"] = nuevas_dates

    history["dates"] = sorted(fechas_vistas)
    save_json(HISTORY_PATH, history)
    print(f"\n[OK] {HISTORY_PATH}: {len(history['dates'])} fechas (1 lectura/dia). "
          f"{len(pivot)} SKUs.")


if __name__ == "__main__":
    main()
