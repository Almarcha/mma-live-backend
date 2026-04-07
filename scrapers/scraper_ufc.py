#!/usr/bin/env python3
"""
MMA Live · Scraper completo UFC
================================
Descarga TODOS los peleadores (activos y retirados) + eventos
y los guarda directamente en Supabase.

Instalación:
    pip install requests beautifulsoup4 lxml supabase python-dotenv tqdm

Uso:
    python scraper_ufc.py --mode fighters   # Solo peleadores
    python scraper_ufc.py --mode events     # Solo eventos
    python scraper_ufc.py --mode all        # Todo (recomendado primera vez)
    python scraper_ufc.py --mode update     # Solo cambios recientes
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client, Client
from tqdm import tqdm

load_dotenv()

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
SUPABASE_URL     = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY     = os.getenv("SUPABASE_SERVICE_KEY", "")   # service_role key
UFC_BASE         = "https://www.ufc.com"
UFC_ATHLETES_URL = "https://www.ufc.com/athletes/all"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY   = 1.5   # segundos entre peticiones (respetuoso con el servidor)
REQUEST_TIMEOUT = 20

# Mapeo de países UFC → código ISO
COUNTRY_MAP = {
    "United States": "US", "USA": "US",
    "Brazil": "BR", "Brasil": "BR",
    "Nigeria": "NG", "Australia": "AU",
    "Canada": "CA", "Mexico": "MX",
    "Russia": "RU", "Georgia": "GE",
    "United Kingdom": "GB", "England": "GB",
    "Ireland": "IE", "New Zealand": "NZ",
    "Poland": "PL", "Netherlands": "NL",
    "France": "FR", "Germany": "DE",
    "Spain": "ES", "Italy": "IT",
    "Japan": "JP", "South Korea": "KR",
    "China": "CN", "Kazakhstan": "KZ",
    "Cameroon": "CM", "Jamaica": "JM",
    "Argentina": "AR", "Colombia": "CO",
    "Chile": "CL", "Peru": "PE",
    "Sweden": "SE", "Norway": "NO",
    "Denmark": "DK", "Finland": "FI",
    "Czech Republic": "CZ", "Serbia": "RS",
    "Croatia": "HR", "Romania": "RO",
    "Ukraine": "UA", "Azerbaijan": "AZ",
    "Armenia": "AM", "Uzbekistan": "UZ",
    "Dagestan": "RU", "Chechnya": "RU",
    "South Africa": "ZA", "Senegal": "SN",
    "Morocco": "MA", "Egypt": "EG",
    "Philippines": "PH", "Thailand": "TH",
    "Indonesia": "ID", "Singapore": "SG",
    "Iran": "IR", "Israel": "IL",
    "Saudi Arabia": "SA", "UAE": "AE",
    "Tunisia": "TN",
}

FLAG_MAP = {
    "US":"🇺🇸","BR":"🇧🇷","NG":"🇳🇬","AU":"🇦🇺","CA":"🇨🇦","MX":"🇲🇽",
    "RU":"🇷🇺","GE":"🇬🇪","GB":"🏴󠁧󠁢󠁥󠁮󠁧󠁿","IE":"🇮🇪","NZ":"🇳🇿","PL":"🇵🇱",
    "NL":"🇳🇱","FR":"🇫🇷","DE":"🇩🇪","ES":"🇪🇸","IT":"🇮🇹","JP":"🇯🇵",
    "KR":"🇰🇷","CN":"🇨🇳","KZ":"🇰🇿","CM":"🇨🇲","JM":"🇯🇲","AR":"🇦🇷",
    "CO":"🇨🇴","CL":"🇨🇱","SE":"🇸🇪","NO":"🇳🇴","DK":"🇩🇰","FI":"🇫🇮",
    "CZ":"🇨🇿","RS":"🇷🇸","HR":"🇭🇷","UA":"🇺🇦","AZ":"🇦🇿","AM":"🇦🇲",
    "UZ":"🇺🇿","ZA":"🇿🇦","SN":"🇸🇳","MA":"🇲🇦","EG":"🇪🇬","PH":"🇵🇭",
    "TH":"🇹🇭","IR":"🇮🇷","IL":"🇮🇱","SA":"🇸🇦","TN":"🇹🇳","RO":"🇷🇴",
}


# ─────────────────────────────────────────
# SUPABASE CLIENT
# ─────────────────────────────────────────
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ ERROR: Define SUPABASE_URL y SUPABASE_SERVICE_KEY en .env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def clean(text) -> str:
    return " ".join(str(text).split()).strip() if text else ""


def safe_get(url: str, retries: int = 3) -> Optional[requests.Response]:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log(f"  Rate limit, esperando {wait}s...")
                time.sleep(wait)
            else:
                log(f"  HTTP {resp.status_code} para {url}")
                return None
        except requests.RequestException as e:
            log(f"  Error ({attempt+1}/{retries}): {e}")
            time.sleep(5)
    return None


def ensure_country(sb: Client, country_name: str) -> Optional[int]:
    """Obtiene o crea un país, devuelve su ID."""
    if not country_name:
        return None

    code = COUNTRY_MAP.get(country_name, country_name[:2].upper())
    flag = FLAG_MAP.get(code, "")

    # Buscar existente
    res = sb.table("countries").select("id").eq("code", code).execute()
    if res.data:
        return res.data[0]["id"]

    # Crear nuevo
    ins = sb.table("countries").insert({
        "code": code, "name": country_name, "flag_emoji": flag
    }).execute()
    return ins.data[0]["id"] if ins.data else None


def parse_height(text: str) -> Optional[float]:
    """'6\' 4"' → 193.0 cm"""
    if not text:
        return None
    m = re.search(r"(\d+)'\s*(\d+)", text)
    if m:
        feet, inches = int(m.group(1)), int(m.group(2))
        return round((feet * 30.48) + (inches * 2.54), 1)
    return None


def parse_reach(text: str) -> Optional[float]:
    """'80"' o '80.5"' → cm"""
    if not text:
        return None
    m = re.search(r"([\d.]+)", text)
    if m:
        return round(float(m.group(1)) * 2.54, 1)
    return None


def parse_record(text: str) -> tuple:
    """'28-4-0' → (28, 4, 0)"""
    if not text:
        return (0, 0, 0)
    m = re.match(r"(\d+)-(\d+)-?(\d+)?", text.strip())
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return (0, 0, 0)


# ─────────────────────────────────────────
# SCRAPER DE PELEADORES
# ─────────────────────────────────────────
def get_athlete_urls() -> list[str]:
    """Obtiene todas las URLs de peleadores desde UFC.com/athletes/all"""
    log("Obteniendo lista de peleadores de UFC.com...")
    urls = []
    page = 0

    while True:
        url = f"{UFC_ATHLETES_URL}?page={page}"
        resp = safe_get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Buscar tarjetas de atletas
        cards = soup.select(
            "a.e-object-card__link, "
            "div.c-listing-athlete-flipcard a[href*='/athlete/'], "
            "a[href*='/athlete/']"
        )

        if not cards:
            log(f"  No hay más peleadores en página {page}")
            break

        new_urls = []
        for card in cards:
            href = card.get("href", "")
            if "/athlete/" in href:
                full_url = f"{UFC_BASE}{href}" if href.startswith("/") else href
                if full_url not in urls:
                    new_urls.append(full_url)

        if not new_urls:
            break

        urls.extend(new_urls)
        log(f"  Página {page}: +{len(new_urls)} peleadores (total: {len(urls)})")
        page += 1
        time.sleep(REQUEST_DELAY)

    log(f"Total URLs encontradas: {len(urls)}")
    return urls


def scrape_fighter_profile(url: str) -> Optional[dict]:
    """Scrapea el perfil completo de un peleador."""
    resp = safe_get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Nombre
    name_el = soup.select_one("h1.hero-profile__name, .c-hero-profile__name, h1[class*='name']")
    if not name_el:
        return None

    full_name = clean(name_el.get_text())
    parts = full_name.split(" ", 1)
    first_name = parts[0]
    last_name   = parts[1] if len(parts) > 1 else ""

    # Nickname
    nick_el = soup.select_one(".hero-profile__nickname, .c-hero-profile__nickname, [class*='nickname']")
    nickname = clean(nick_el.get_text()).strip('"\'') if nick_el else None

    # Récord
    record_el = soup.select_one(".hero-profile__division-body, [class*='record']")
    record_text = clean(record_el.get_text()) if record_el else ""
    wins, losses, draws = parse_record(record_text)

    # Categoría de peso
    division_el = soup.select_one(".hero-profile__division-title, [class*='division']")
    weight_class_raw = clean(division_el.get_text()) if division_el else ""

    # Slug de la URL
    slug = url.rstrip("/").split("/")[-1]

    # Stats del peleador
    stats = {}
    stat_labels = soup.select(".c-stat-compare__label, [class*='stat-label']")
    stat_values = soup.select(".c-stat-compare__number, [class*='stat-number']")
    for label, value in zip(stat_labels, stat_values):
        key = clean(label.get_text()).lower().replace(" ", "_")
        stats[key] = clean(value.get_text())

    # Datos personales del bio
    bio = {}
    bio_items = soup.select(".c-bio__field, [class*='bio__field']")
    for item in bio_items:
        label_el = item.select_one(".c-bio__label, [class*='bio__label']")
        value_el = item.select_one(".c-bio__text, [class*='bio__text']")
        if label_el and value_el:
            key = clean(label_el.get_text()).lower().replace(" ", "_")
            bio[key] = clean(value_el.get_text())

    # Imagen
    img_el = soup.select_one(".hero-profile__image img, [class*='hero'] img")
    img_url = img_el.get("src", "") if img_el else ""

    # Status: activo o retirado
    status_el = soup.select_one("[class*='status'], [class*='retired']")
    status_text = clean(status_el.get_text()).lower() if status_el else ""
    status = "Retired" if "retired" in status_text or "retirado" in status_text else "Active"

    # País / Nacionalidad
    nationality = bio.get("nationality", bio.get("hometown", ""))
    hometown    = bio.get("hometown", "")

    # Físico
    height_raw = bio.get("height", stats.get("height", ""))
    reach_raw  = bio.get("reach",  stats.get("reach",  ""))

    return {
        "ufc_slug":             slug,
        "ufc_profile_url":      url,
        "first_name":           first_name,
        "last_name":            last_name,
        "nickname":             nickname,
        "wins":                 wins,
        "losses":               losses,
        "draws":                draws,
        "status":               status,
        "height_cm":            parse_height(height_raw),
        "reach_cm":             parse_reach(reach_raw),
        "stance":               bio.get("stance"),
        "profile_image_url":    img_url if img_url.startswith("http") else None,
        "nationality_raw":      nationality,
        "hometown_raw":         hometown,
        "weight_class_raw":     weight_class_raw,
        "last_scraped_at":      datetime.now(timezone.utc).isoformat(),
    }


def upsert_fighter(sb: Client, data: dict) -> bool:
    """Inserta o actualiza un peleador en Supabase."""
    try:
        # Resolver país
        nat_id = None
        if data.get("nationality_raw"):
            nat_id = ensure_country(sb, data["nationality_raw"])

        payload = {
            "ufc_slug":          data["ufc_slug"],
            "ufc_profile_url":   data["ufc_profile_url"],
            "first_name":        data["first_name"],
            "last_name":         data["last_name"],
            "nickname":          data.get("nickname"),
            "wins":              data["wins"],
            "losses":            data["losses"],
            "draws":             data["draws"],
            "status":            data["status"],
            "height_cm":         data.get("height_cm"),
            "reach_cm":          data.get("reach_cm"),
            "stance":            data.get("stance"),
            "profile_image_url": data.get("profile_image_url"),
            "nationality_id":    nat_id,
            "last_scraped_at":   data["last_scraped_at"],
        }

        # upsert por ufc_slug
        sb.table("fighters").upsert(
            payload,
            on_conflict="ufc_slug"
        ).execute()
        return True

    except Exception as e:
        log(f"  ERROR guardando {data.get('ufc_slug')}: {e}")
        return False


def scrape_all_fighters(sb: Client, limit: Optional[int] = None):
    """Scrapea todos los peleadores de UFC.com."""
    started_at = datetime.now(timezone.utc)
    log("=" * 55)
    log("SCRAPER DE PELEADORES · UFC.com")
    log("=" * 55)

    urls = get_athlete_urls()
    if limit:
        urls = urls[:limit]
        log(f"Modo TEST: procesando solo {limit} peleadores")

    new_count = upd_count = err_count = 0

    for url in tqdm(urls, desc="Peleadores", unit="fighter"):
        data = scrape_fighter_profile(url)
        if not data:
            err_count += 1
            continue

        # Comprobar si existe
        existing = sb.table("fighters").select("id").eq("ufc_slug", data["ufc_slug"]).execute()
        ok = upsert_fighter(sb, data)

        if ok:
            if existing.data:
                upd_count += 1
            else:
                new_count += 1
        else:
            err_count += 1

        time.sleep(REQUEST_DELAY)

    # Registrar en scraper_log
    sb.table("scraper_log").insert({
        "scraper":      "ufc_fighters",
        "status":       "success" if err_count == 0 else "partial",
        "records_new":  new_count,
        "records_upd":  upd_count,
        "records_err":  err_count,
        "message":      f"Total URLs: {len(urls)}",
        "started_at":   started_at.isoformat(),
        "finished_at":  datetime.now(timezone.utc).isoformat(),
    }).execute()

    log(f"\n✅ Peleadores: {new_count} nuevos · {upd_count} actualizados · {err_count} errores")


# ─────────────────────────────────────────
# SCRAPER DE EVENTOS
# ─────────────────────────────────────────
def scrape_events(sb: Client):
    """Scrapea eventos próximos y pasados de UFC.com."""
    started_at = datetime.now(timezone.utc)
    log("=" * 55)
    log("SCRAPER DE EVENTOS · UFC.com")
    log("=" * 55)

    resp = safe_get(f"{UFC_BASE}/events")
    if not resp:
        log("ERROR: No se pudo acceder a UFC.com/events")
        return

    soup = BeautifulSoup(resp.text, "lxml")
    new_count = upd_count = err_count = 0

    event_links = set()
    for a in soup.select("a[href*='/event/']"):
        href = a.get("href", "")
        if href:
            full = f"{UFC_BASE}{href}" if href.startswith("/") else href
            event_links.add(full)

    log(f"Eventos encontrados: {len(event_links)}")

    for url in tqdm(event_links, desc="Eventos", unit="event"):
        data = scrape_event_detail(url)
        if not data:
            err_count += 1
            continue

        slug = url.rstrip("/").split("/")[-1]
        existing = sb.table("events").select("id").eq("ufc_slug", slug).execute()

        try:
            payload = {
                "ufc_slug":    slug,
                "name":        data["name"],
                "event_type":  data["event_type"],
                "event_date":  data["event_date"],
                "venue":       data.get("venue"),
                "city":        data.get("city"),
                "status":      data["status"],
                "broadcast":   data.get("broadcast"),
                "ufc_url":     url,
                "last_scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            sb.table("events").upsert(payload, on_conflict="ufc_slug").execute()
            if existing.data:
                upd_count += 1
            else:
                new_count += 1
        except Exception as e:
            log(f"  ERROR evento {slug}: {e}")
            err_count += 1

        time.sleep(REQUEST_DELAY)

    sb.table("scraper_log").insert({
        "scraper":     "ufc_events",
        "status":      "success" if err_count == 0 else "partial",
        "records_new": new_count,
        "records_upd": upd_count,
        "records_err": err_count,
        "started_at":  started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    log(f"\n✅ Eventos: {new_count} nuevos · {upd_count} actualizados · {err_count} errores")


def scrape_event_detail(url: str) -> Optional[dict]:
    """Extrae datos de un evento."""
    resp = safe_get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    name_el = soup.select_one("h1, .e-col-9 h1, [class*='event-title']")
    if not name_el:
        return None

    name = clean(name_el.get_text())

    date_el = soup.select_one("[class*='date'], time")
    date_str = clean(date_el.get_text()) if date_el else ""

    venue_el = soup.select_one("[class*='venue'], [class*='location']")
    venue = clean(venue_el.get_text()) if venue_el else ""

    broadcast_el = soup.select_one("[class*='broadcast'], [class*='network']")
    broadcast = clean(broadcast_el.get_text()) if broadcast_el else ""

    event_type = "Numbered" if re.search(r'\bUFC\s+\d{3}\b', name) else "Fight Night"
    status = "Upcoming"

    # Intentar parsear fecha
    event_date = None
    date_match = re.search(r'(\w+ \d+,?\s*\d{4})', date_str)
    if date_match:
        try:
            from datetime import datetime
            dt = datetime.strptime(date_match.group(1).replace(",", ""), "%B %d %Y")
            event_date = dt.strftime("%Y-%m-%d")
            if dt.date() < datetime.now().date():
                status = "Completed"
        except ValueError:
            pass

    if not event_date:
        return None

    return {
        "name":       name,
        "event_type": event_type,
        "event_date": event_date,
        "venue":      venue,
        "city":       venue,
        "status":     status,
        "broadcast":  broadcast,
    }


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MMA Live UFC Scraper")
    parser.add_argument(
        "--mode",
        choices=["fighters", "events", "all", "update", "test"],
        default="all",
        help="Qué scraper ejecutar"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Límite de peleadores (para pruebas)"
    )
    args = parser.parse_args()

    sb = get_supabase()
    log(f"✅ Conectado a Supabase: {SUPABASE_URL[:40]}...")

    if args.mode in ("fighters", "all"):
        scrape_all_fighters(sb, limit=args.limit if args.mode == "test" else None)

    if args.mode in ("events", "all", "update"):
        scrape_events(sb)

    if args.mode == "test":
        scrape_all_fighters(sb, limit=args.limit or 10)
        scrape_events(sb)

    log("\n🏁 Scraping completado.")
