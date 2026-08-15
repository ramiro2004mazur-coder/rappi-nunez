# Rappi · Nunez — historico de precios de cerveza

Scraper + dashboard automatizado para trackear precios de cerveza en la
tienda de Rappi Turbo de Monroe (store_id 166964, zona "Nunez"). Corre 2
veces por dia (10:15 y 19:00 ART), consolida el historico y publica el
dashboard en GitHub Pages. Hermano de [pedidosya-nunez](https://github.com/ramiro2004mazur-coder/pedidosya-nunez)
(mismo formato de datos y mismo dashboard, plataforma distinta).

## Estructura

```
scraper/scrape.py          scraper (Playwright, sin login), 1 sola tienda
data/history.json          historico consolidado, fuente de verdad (AM/PM por dia)
data/catalog.json          clasificacion marca/sku -> grupo (CMQ/Competencia) y segmento
data/fights_config.json    definicion de las "luchas" CMQ vs Competencia
data/raw/                  snapshot crudo de cada corrida (auditoria)
data/logs/                 avisos de SKUs sin clasificar / filas descartadas
docs/index.html            dashboard (esto es lo que sirve GitHub Pages)
docs/data.json             generado, no se edita a mano
scripts/ingest_run.py      mergea 1 corrida nueva en data/history.json
scripts/build_dashboard_data.py   data/history.json -> docs/data.json (stats/fights)
.github/workflows/scrape_and_deploy.yml   cron 10:15 y 19:00 ART
```

## Por que Playwright y no requests

La pagina de Rappi Turbo (`/tiendas/{store_id}-turbo-express/cervezas`) es
Next.js con SSR: la carga inicial trae los productos embebidos en
`__NEXT_DATA__` sin necesidad de login. Pero cada subcategoria solo entrega
~24 productos en esa carga inicial aunque tenga muchos mas — el resto sale
haciendo click en "Ver mas", que dispara un POST a un endpoint interno que
exige un "device id" generado por el navegador. Por eso el scraper usa un
navegador real (Playwright) y clickea "Ver mas" hasta agotar cada
subcategoria, en vez de pegarle a la API con `requests` plano.

El JSON de cada producto ya trae fleje/precio/dinamica resueltos:
`real_price` (fleje), `price` (PTC), `discount` (dinamica, 0-1).

## Setup unico (a hacer vos, no lo hace el workflow)

1. Crear el repo en GitHub (ej. `rappi-nunez`) y pushear este proyecto.
2. **Settings → Pages → Source: "Deploy from a branch" → Branch: `main` / `docs`.**
   Cada vez que el workflow commitea un cambio en `docs/data.json`, GitHub
   Pages se re-despliega solo.
3. Revisar `data/logs/ingest_warnings.log` despues de las primeras corridas:
   los SKUs de Rappi que no existian en el catalogo heredado de PedidosYa
   quedan como "Sin clasificar" — completalos a mano en `data/catalog.json`.
4. A diferencia de PedidosYa, Rappi **no bloquea las IPs de datacenter de
   GitHub Actions** (confirmado con el scraper de frio de `rappi-turbo-frio`,
   que ya corre 2x/dia en la nube sin problema), asi que el cron de este
   workflow queda activo desde el arranque — no hace falta corrida local.

## Historico pre-existente (backfill)

El repo ya arranca con 9 cortes cargados: 7 dias sueltos (05, 06, 09, 10,
11, 12, 13 de agosto, un corte AM cada uno) mas hoy (15/08, AM y PM
reales). Los 7 primeros vienen de CSVs sueltos que se habian scrapeado a
mano antes de armar este repo, importados con
`scripts/import_legacy_csv.py`. Ese script no es parte del pipeline (no
lo corre el workflow), es un backfill de una sola vez, pero documentar
que hace importa porque esos CSV originales tenian dos problemas reales
que corrigio en el import:

- La columna `precio` en la mayoria de esos archivos no era el precio
  real sino un precio-por-ml mal capturado (ej. fleje $3749, "precio"
  $5.16). Se detecto comparando contra la formula real de Rappi
  (`precio = fleje * (1 - descuento)`, confirmada contra la API en vivo)
  y se recalculo el precio real a partir de fleje + el % de descuento en
  vez de confiar en esa columna.
- Regla ya documentada en el alert del dashboard: **"100% OFF" es un
  placeholder de Rappi para "sin dinamica activa", no un descuento real**
  (nunca hay cerveza gratis) → se trata como 0%. Aplica tanto al import
  del historico viejo como al scraper en vivo (`scraper/scrape.py`), por
  si Rappi devuelve `discount: 1.0` en alguna corrida futura.

Tambien se descartaron filas basura de scrapeos viejos que habian
capturado texto de UI como si fuera producto ("Agregar", "Patrocinado",
"Pronto de vuelta") y se excluyeron packs/combos, igual que en el
scraper en vivo.

## Correr manualmente

```bash
pip install -r scraper/requirements.txt
playwright install chromium
python3 scraper/scrape.py --slot AM          # o --slot PM, o sin flag (autodetecta)
python3 scripts/ingest_run.py --csv data/raw/2026-08-15_AM.csv --date 2026-08-15 --slot AM
python3 scripts/build_dashboard_data.py
```

## Formato de `data/history.json`

Identico al de `pedidosya-nunez` (mismo dashboard, misma forma de datos):

```json
{
  "meta": {"tienda": "Nunez", "plataforma": "Rappi Turbo"},
  "dates": ["2026-08-15_AM", "2026-08-15_PM"],
  "pivot": [
    {
      "id": "brahma-cerveza-brahma-chopp-lata-354-ml",
      "marca": "Brahma",
      "sku": "Cerveza Brahma Chopp Lata 354 ml",
      "calibre": "330/355",
      "grupo": "CMQ",
      "segmento": "Core",
      "dates": {
        "2026-08-15_AM": {"fleje": 1929.0, "ptc": 1736.1, "dinamica": 0.1},
        "2026-08-15_PM": {"fleje": 1929.0, "ptc": 1350.3, "dinamica": 0.3}
      }
    }
  ]
}
```
