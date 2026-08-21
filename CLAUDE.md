# rappi-nunez

## 1. Qué es

Scraper + dashboard automatizado que trackea el histórico de precios de
cerveza en **Rappi Turbo**, en un único dark store: **"Belgrano 1" /
Monroe 1616** (store_id `166964`, zona interna `"Nunez"`, CABA).

Registra por SKU y por día: fleje (precio de lista), PTC (precio final
con descuento aplicado) y dinámica (% de descuento vigente), separando
marcas **CMQ** (Cervecería y Maltería Quilmes / AB InBev Argentina) vs.
**Competencia**, para poder comparar evolución de precios entre ambas.

Es hermano de dos proyectos con el mismo patrón (mismo formato de datos,
mismo dashboard base):
- [`pedidosya-nunez`](https://github.com/ramiro2004mazur-coder/pedidosya-nunez) — mismo tracking, plataforma PedidosYa Market.
- `rappi-turbo-frio` — trackea el badge de "entrega en frío" (no precios) en 27 dark stores de Rappi Turbo. Proyecto distinto, no confundir.

## 2. Cómo correrlo manualmente

```bash
pip install -r scraper/requirements.txt
playwright install chromium

python3 scraper/scrape.py
python3 scripts/ingest_run.py --csv data/raw/2026-08-20.csv --date 2026-08-20
python3 scripts/build_dashboard_data.py
```

- `scraper/scrape.py` scrapea el store y escribe `data/raw/YYYY-MM-DD.csv`
  (usa la fecha de hoy en horario ART si no se pasa `--date`).
- `scripts/ingest_run.py` mergea ese CSV en `data/history.json` (el
  histórico consolidado, fuente de verdad).
- `scripts/build_dashboard_data.py` recalcula `docs/data.json` (lo que
  lee el dashboard) a partir de `data/history.json`.

Scripts que **no** son parte del pipeline normal (se corrieron una sola
vez, quedan documentados por si hace falta repetir algo parecido):
`scripts/migrate_am_pm.py` (migración 2 corridas/día → 1), 
`scripts/import_legacy_csv.py` (backfill de CSVs sueltos previos al repo),
`scripts/seed_catalog.py` (clasificación inicial CMQ/Competencia por marca).

## 3. Estructura

### Lógica de scraping (`scraper/scrape.py`)

La página de categoría de Rappi Turbo (`/tiendas/{store_id}-turbo-express/cervezas`)
es Next.js con SSR: la carga inicial trae productos embebidos en
`__NEXT_DATA__` **sin necesidad de login**. Pero cada subcategoría solo
entrega ~24 productos en esa carga inicial aunque tenga más — el resto
sale haciendo click en "Ver más", que dispara un POST a un endpoint
interno que exige un "device id" generado por el navegador. Por eso el
scraper usa **Playwright** (navegador real) en vez de `requests` plano:
entra a cada subcategoría y clickea "Ver más" hasta agotarla.

El JSON de cada producto ya trae los tres campos resueltos:
- `real_price` → fleje
- `price` → PTC (precio final)
- `discount` → dinámica, como fracción 0–1

Se excluyen packs/combos/sixpacks (por `attributes.pack_size` o por
nombre). Si un producto individual falla al parsearse, se loguea y se
sigue; si la tienda entera no devuelve productos, el proceso sale con
código de error.

**Regla especial:** Rappi usa `"100% OFF"` / `discount: 1.0` como
placeholder de "sin dinámica activa", **no** como un descuento real
(nunca hay cerveza gratis) → se trata como 0%. Ver `scraper/scrape.py`.

### Datos históricos

- **`data/history.json`** — fuente de verdad. Un objeto por SKU con su
  serie temporal completa:
  ```json
  {
    "meta": {"tienda": "Nunez", "plataforma": "Rappi Turbo"},
    "dates": ["2026-08-20", "2026-08-21"],
    "pivot": [
      {
        "id": "brahma-cerveza-brahma-chopp-lata-354-ml",
        "marca": "Brahma", "sku": "Cerveza Brahma Chopp Lata 354 ml",
        "calibre": "330/355", "grupo": "CMQ", "segmento": "Core",
        "dates": {
          "2026-08-20": {"fleje": 1929.0, "ptc": 1736.1, "dinamica": 0.1},
          "2026-08-21": {"fleje": 1929.0, "ptc": 1350.3, "dinamica": 0.3}
        }
      }
    ]
  }
  ```
  1 fecha = 1 lectura diaria (ver sección 4 sobre el cambio de 2 a 1
  corrida/día).
- **`data/catalog.json`** — clasificación marca/SKU → `grupo`
  (CMQ/Competencia) y `segmento`. SKUs nuevos que el scraper encuentra y
  no están acá quedan como `"Sin clasificar"` y se loguean en
  `data/logs/ingest_warnings.log` para completarlos a mano.
- **`data/fights_config.json`** — enfrentamientos predefinidos CMQ vs.
  Competencia, usados como accesos rápidos en la pestaña "Comparar" del
  dashboard.
- **`data/raw/YYYY-MM-DD.csv`** — snapshot crudo de cada corrida, para
  auditoría (no se lee para reconstruir el histórico, solo para
  reprocesar si hace falta).
- **`docs/data.json`** — generado por `build_dashboard_data.py`, es lo
  que consume `docs/index.html`. No se edita a mano.

## 4. Automatización

GitHub Actions (`.github/workflows/scrape_and_deploy.yml`):
- **Cron: `15 13 * * *` UTC = 10:15 ART, 1 vez por día.** (Hasta el
  18/08 corría 2 veces por día, AM y PM, para ver variación intradía; se
  confirmó que la dinámica no cambia según la hora y se simplificó a 1
  corrida. El histórico previo con AM/PM se migró con
  `scripts/migrate_am_pm.py`.)
- También se puede disparar a mano (`workflow_dispatch`).
- Pasos: instala Playwright/Chromium → scrapea → ingesta al histórico →
  regenera `docs/data.json` → commit + push (solo si hubo cambios) → si
  hay errores de fila, los sube como artifact.
- **Corre 100% en la nube**, sin depender de que ninguna máquina esté
  prendida — a diferencia de `pedidosya-nunez`, Rappi no bloquea las IPs
  de datacenter de GitHub Actions.
- El push a `main` dispara el redeploy de GitHub Pages (`docs/` como
  raíz publicada).

## 5. Reglas importantes

- **No modificar la lógica de parseo de precios** (`scraper/scrape.py`:
  extracción de `real_price`/`price`/`discount`, la regla de "100% OFF =
  0%", el cálculo de dinámica en `scripts/ingest_run.py`) **sin avisar
  antes.** Es lógica ya validada contra la API en vivo de Rappi y contra
  bugs reales encontrados en el histórico previo (ver README, sección
  "Historico pre-existente") — un cambio silencioso ahí puede corromper
  el histórico sin que se note hasta mucho después.

- **Sanity check pendiente de implementar:** los precios que se desvíen
  más de 50% respecto al valor del día anterior para el mismo SKU deben
  **flaguearse, no guardarse directo como válidos**. Esto todavía **no
  existe** en `scripts/ingest_run.py` — hoy cualquier valor que pase el
  parseo se guarda sin comparar contra la corrida anterior. Al
  implementarlo: comparar contra el último `ptc` conocido de ese `id` en
  `history.json` antes de sobreescribir, y loguear en
  `data/logs/ingest_warnings.log` (mismo mecanismo que las demás filas
  descartadas/dudosas) en vez de cortar la corrida.

## 6. Estado actual

- **Cobertura:** 1 sola tienda/zona — Rappi Turbo, dark store Monroe
  (store_id 166964), zona "Nunez", CABA. No cubre otras zonas ni otras
  plataformas (eso es lo que separa a este repo de sus hermanos).
- **Histórico:** 14 fechas cargadas (05, 06, 09, 10, 11, 12, 13, 15, 16,
  17, 18, 19, 20 y 21 de agosto de 2026 — el 14/08 no tiene corrida).
- **Catálogo:** 318 SKUs clasificados (113 CMQ, 202 Competencia, 3 aún
  "Sin clasificar" pendientes de revisar a mano en `data/catalog.json`).
- **Automatización:** activa y corriendo sola en GitHub Actions desde el
  15/08, sin intervención manual salvo por fallas puntuales de la corrida
  automática (cron demorado, etc.), que se resuelven disparando el
  workflow a mano.
- Dashboard publicado en GitHub Pages: `docs/index.html` /
  `docs/data.json`.
