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
