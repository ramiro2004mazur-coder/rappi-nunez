# Rappi · Nunez — historico de precios de cerveza

Scraper + dashboard automatizado para trackear precios de cerveza en la
tienda de Rappi Turbo de Monroe (store_id 166964, zona "Nunez"). Corre 1
vez por dia (10:15 ART), consolida el historico y publica el dashboard en
GitHub Pages. Hermano de [pedidosya-nunez](https://github.com/ramiro2004mazur-coder/pedidosya-nunez)
(mismo formato de datos y mismo dashboard, plataforma distinta).

## Estructura

```
scraper/scrape.py          scraper (Playwright, sin login), 1 sola tienda
data/history.json          historico consolidado, fuente de verdad (1 fecha = 1 lectura)
data/catalog.json          clasificacion marca/sku -> grupo (CMQ/Competencia) y segmento
data/fights_config.json    "luchas" CMQ vs competencia, accesos rapidos de la pestana Comparar
data/raw/                  snapshot crudo de cada corrida (auditoria)
data/logs/                 avisos de SKUs sin clasificar / filas descartadas
docs/index.html            dashboard (esto es lo que sirve GitHub Pages)
docs/data.json             generado, no se edita a mano
scripts/ingest_run.py      mergea 1 corrida nueva en data/history.json
scripts/build_dashboard_data.py   data/history.json -> docs/data.json (stats/fights)
scripts/migrate_am_pm.py   migracion unica (05/08-18/08: paso de 2 corridas/dia a 1)
.github/workflows/scrape_and_deploy.yml   cron 10:15 ART
```

## Dashboard

Mismas pestanas que `pedidosya-nunez`: **Evolucion por SKU** (tabla con
fleje/PTC/dinamica por dia, click en un producto abre su grafico
individual), **Comparar** (elegi cualquier cantidad de SKUs de cualquier
marca — no solo CMQ — y ves su evolucion superpuesta en un grafico +
tabla comparativa; los accesos rapidos precargan un enfrentamiento CMQ
vs competencia ya armado desde `data/fights_config.json`), **Heatmap
dinamica**, **Cambios** (ultimo dia vs anterior) e **Insights**.

La vieja pestana "Luchas" se fusiono dentro de Comparar (antes mostraba
una grilla de tablas dificil de leer; ahora es el mismo comparador
general, con los enfrentamientos predefinidos como atajo de seleccion).

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
   que ya corre 1x/dia en la nube sin problema), asi que el cron de este
   workflow queda activo desde el arranque — no hace falta corrida local.

## De 2 corridas diarias a 1

Hasta el 18/08 corria 2 veces por dia (AM/PM) para ver variacion
intradia; se confirmo que la dinamica no cambia segun la hora del dia,
asi que se paso a 1 sola lectura diaria (10:15 ART). El historico previo
que tenia ambas corridas se migro una sola vez con
`scripts/migrate_am_pm.py`: por cada fecha con AM y PM, se quedo con la
que tuviera mas SKUs scrapeados (empate → PM), descartando la otra
entera (no se promedian ni combinan). Las fechas que ya eran una sola
lectura solo se renombraron sin el sufijo `_AM`/`_PM`.

## Historico pre-existente (backfill del 05/08-13/08)

Antes de armar este repo ya habia 7 CSVs sueltos scrapeados a mano
(05, 06, 09, 10, 11, 12, 13 de agosto), importados con
`scripts/import_legacy_csv.py` (no es parte del pipeline, backfill de una
sola vez). Documentado porque corrigio dos problemas reales de esos CSV:

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
python3 scraper/scrape.py
python3 scripts/ingest_run.py --csv data/raw/2026-08-20.csv --date 2026-08-20
python3 scripts/build_dashboard_data.py
```

## Formato de `data/history.json`

Identico al de `pedidosya-nunez` (mismo dashboard, misma forma de datos):

```json
{
  "meta": {"tienda": "Nunez", "plataforma": "Rappi Turbo"},
  "dates": ["2026-08-17", "2026-08-18"],
  "pivot": [
    {
      "id": "brahma-cerveza-brahma-chopp-lata-354-ml",
      "marca": "Brahma",
      "sku": "Cerveza Brahma Chopp Lata 354 ml",
      "calibre": "330/355",
      "grupo": "CMQ",
      "segmento": "Core",
      "dates": {
        "2026-08-17": {"fleje": 1929.0, "ptc": 1736.1, "dinamica": 0.1},
        "2026-08-18": {"fleje": 1929.0, "ptc": 1350.3, "dinamica": 0.3}
      }
    }
  ]
}
```
