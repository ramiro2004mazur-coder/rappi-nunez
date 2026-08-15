"""Funciones y rutas compartidas por los scripts de migracion/ingesta/build."""

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
LOGS_DIR = DATA_DIR / "logs"
DOCS_DIR = ROOT / "docs"

HISTORY_PATH = DATA_DIR / "history.json"
CATALOG_PATH = DATA_DIR / "catalog.json"
FIGHTS_PATH = DATA_DIR / "fights_config.json"
DASHBOARD_DATA_PATH = DOCS_DIR / "data.json"

CSV_FIELDS = ["zona", "marca", "descripcion", "calibre", "fleje", "precio", "descuento"]

# Buckets de calibre usados por el dashboard (igual que el data.json historico).
CALIBRE_BUCKETS = [
    (275, "275"),
    (355, "330/355"),
    (473, "473"),
    (600, "600"),
    (730, "710/730"),
]


def normalize(s):
    """minusculas, sin tildes, sin espacios/puntuacion redundante -> clave de match estable."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def catalog_key(marca, descripcion):
    return normalize(marca) + "|" + normalize(descripcion)


def slugify(marca, descripcion):
    base = normalize(marca) + "-" + normalize(descripcion)
    base = re.sub(r"\s+", "-", base.strip())
    return re.sub(r"-+", "-", base)


def parse_calibre_ml(raw_calibre):
    """'473 ml' / '473ml' / '-' -> 473 o None."""
    if not raw_calibre:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(raw_calibre))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def bucket_calibre(raw_calibre):
    ml = parse_calibre_ml(raw_calibre)
    if ml is None:
        return "S/C"
    for limit, label in CALIBRE_BUCKETS:
        if ml <= limit:
            return label
    return "710/730"


def load_json(path, default):
    if not Path(path).exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def log_warning(message, log_file=None):
    print(f"[WARN] {message}")
    if log_file:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGS_DIR / log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")
