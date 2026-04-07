#!/usr/bin/env python3
"""
MMA Live · Scraper robusto
===========================
Usa ufcstats.com (más estable que ufc.com) para eventos y combates.
Usa ufc.com solo para perfiles de peleadores.

Instalación:
    pip install requests beautifulsoup4 lxml supabase==1.2.0 python-dotenv tqdm

Uso:
    python scraper_ufc.py --mode events      # Eventos + combates (rápido, ~2 min)
    python scraper_ufc.py --mode fighters    # Todos los peleadores (~2-3 horas)
    python scraper_ufc.py --mode all         # Todo
    python scraper_ufc.py --mode test        # 10 peleadores para probar
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
from tqdm import tqdm

load_dotenv()

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

try:
    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
except Exception as e:
    print(f"[WARN] No se pudo conectar a Supabase: {e}")
    sb = None

# ── Constantes ────────────────────────────────────────────
UFCSTATS_EVENTS  = "http://ufcstats.com/statistics/events/completed?page=all"
UFCSTATS_UPCOMING = "http://ufcstats.com/statistics/events/upcoming?page=all"
UFC_ATHLETES_URL = "https://www.ufc.com/athletes/all"
UFC_BASE         = "https://www.ufc.com"
DELAY            = 1.2   # segundos entre peticiones

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

COUNTRY_MAP = {
    "United States":"US","USA":"US","Brazil":"BR","Nigeria":"NG","Australia":"AU",
    "Canada":"CA","Mexico":"MX","Russia":"RU","Georgia":"GE","England":"GB",
    "United Kingdom":"GB","Ireland":"IE","New Zealand":"NZ","Poland":"PL",
    "Netherlands":"NL","France":"FR","Germany":"DE","Spain":"ES","Italy":"IT",
    "Japan":"JP","South Korea":"KR","China":"CN","Kazakhstan":"KZ","Sweden":"SE",
    "Norway":"NO","Denmark":"DK","Czech Republic":"CZ","Serbia":"RS","Ukraine":"UA",
    "Azerbaijan":"AZ","Armenia":"AM","Uzbekistan":"UZ","South Africa":"ZA",
    "Morocco":"MA","Philippines":"PH","Thailand":"TH","Iran":"IR","Tunisia":"TN",
    "Jamaica":"JM","Argentina":"AR","Colombia":"CO","Chile":"CL","Cameroon":"CM",
    "Romania":"RO","Scotland":"GB","Wales":"GB","Puerto Rico":"US","Dagestan":"RU",
}

FLAG_MAP = {
    "US":"🇺🇸","BR":"🇧🇷","NG":"🇳🇬","AU":"🇦🇺","CA":"🇨🇦","MX":"🇲🇽",
    "RU":"🇷🇺","GE":"🇬🇪","GB":"🏴󠁧󠁢󠁥󠁮󠁧󠁿","IE":"🇮🇪","NZ":"🇳🇿","PL":"🇵🇱",
    "NL":"🇳🇱","FR":"🇫🇷","DE":"🇩🇪","ES":"🇪🇸","IT":"🇮🇹","JP":"🇯🇵",
    "KR":"🇰🇷","CN":"🇨🇳","KZ":"🇰🇿","SE":"🇸🇪","NO":"🇳🇴","DK":"🇩🇰",
    "CZ":"🇨🇿","RS":"🇷🇸","UA":"🇺🇦","AZ":"🇦🇿","AM":"🇦🇲","UZ":"🇺🇿",
    "ZA":"🇿🇦","MA":"🇲🇦","PH":"🇵🇭","TH":"🇹🇭","IR":"🇮🇷","TN":"🇹🇳",
    "JM":"🇯🇲","AR":"🇦🇷","CO":"🇨🇴","CL":"🇨🇱","CM":"🇨🇲","RO":"🇷🇴",
}


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clean(t) -> str:
    return " ".join(str(t).split()).strip() if t else ""

def safe_get(url, retries=3) -> Optional[requests.Response]:
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(15 * (i + 1))
            else:
                log(f"  HTTP {r.status_code} → {url[:80]}")
                return None
        except Exception as e:
            log(f"  Error ({i+1}/{retries}): {e}")
            time.sleep(5)
    return None

def ensure_country(name: str) -> Optional[int]:
    if not sb or not name:
        return None
    code = COUNTRY_MAP.get(name, name[:2].upper())
    flag = FLAG_MAP.get(code, "")
    try:
        res = sb.table("countries").select("id").eq("code", code).execute()
        if res.data:
            return res.data[0]["id"]
        ins = sb.table("countries").insert({"code": code, "name": name, "flag_emoji": flag}).execute()
        return ins.data[0]["id"] if ins.data else None
    except:
        return None

def parse_height(t) -> Optional[float]:
    if not t: return None
    m = re.search(r"(\d+)'\s*(\d+)", t)
    if m: return round(int(m.group(1))*30.48 + int(m.group(2))*2.54, 1)
    return None

def parse_reach(t) -> Optional[float]:
    if not t: return None
    m = re.search(r"([\d.]+)", t)
    return round(float(m.group(1))*2.54, 1) if m else None

def parse_record(t) -> tuple:
    if not t: return (0,0,0)
    m = re.match(r"(\d+)-(\d+)-?(\d+)?", t.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else (0,0,0)

def parse_date(t) -> Optional[str]:
    if not t: return None
    for fmt in ["%B %d, %Y", "%b %d, %Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(clean(t), fmt).strftime("%Y-%m-%d")
        except: pass
    return None

def classify_event(name: str) -> str:
    if re.search(r'\bUFC\s+\d{3}\b', name): return "Numbered"
    if "fight night" in name.lower():        return "Fight Night"
    if any(w in name.lower() for w in ["freedom","white house","special"]): return "Special"
    return "Fight Night"


# ─────────────────────────────────────────
# SCRAPER DE EVENTOS — ufcstats.com
# (mucho más fiable que ufc.com)
# ─────────────────────────────────────────
def scrape_events():
    if not sb:
        log("❌ Sin conexión a Supabase"); return

    log("="*55)
    log("SCRAPER EVENTOS · ufcstats.com")
    log("="*55)

    new_c = upd_c = err_c = 0
    started = datetime.now(timezone.utc)

    # Próximos eventos
    upcoming = _get_event_list(UFCSTATS_UPCOMING, status="Upcoming")
    log(f"  Próximos: {len(upcoming)} eventos")

    # Pasados (últimas 2 páginas para tener histórico reciente)
    past = _get_event_list(UFCSTATS_EVENTS, status="Completed")
    log(f"  Pasados: {len(past)} eventos")

    all_events = upcoming + past

    for ev in tqdm(all_events, desc="Eventos", unit="ev"):
        try:
            existing = sb.table("events").select("id").eq("ufc_slug", ev["ufc_slug"]).execute()
            sb.table("events").upsert(ev, on_conflict="ufc_slug").execute()

            # Scrapear combates del evento si tiene URL
            if ev.get("ufc_url") and ev.get("ufc_slug"):
                _scrape_event_fights(ev["ufc_slug"], ev.get("ufc_url",""))

            if existing.data: upd_c += 1
            else: new_c += 1
        except Exception as e:
            log(f"  ERROR evento {ev.get('ufc_slug')}: {e}")
            err_c += 1
        time.sleep(DELAY)

    _log_scraper("ufc_events", new_c, upd_c, err_c, started)
    log(f"✅ Eventos: {new_c} nuevos · {upd_c} actualizados · {err_c} errores")


def _get_event_list(url: str, status: str) -> list[dict]:
    resp = safe_get(url)
    if not resp: return []

    soup = BeautifulSoup(resp.text, "lxml")
    rows = soup.select("tr.b-statistics__table-row")
    events = []

    for row in rows:
        cols = row.select("td")
        if len(cols) < 2: continue

        link = row.select_one("a")
        if not link: continue

        name     = clean(link.get_text())
        href     = link.get("href","")
        date_txt = clean(cols[1].get_text()) if len(cols) > 1 else ""
        location = clean(cols[2].get_text()) if len(cols) > 2 else ""

        if not name or not href: continue

        slug     = href.rstrip("/").split("/")[-1]
        ev_date  = parse_date(date_txt)
        if not ev_date: continue

        # Parsear ciudad y país de la localización
        loc_parts = [p.strip() for p in location.split(",") if p.strip()]
        city    = loc_parts[0] if loc_parts else ""
        country = loc_parts[-1] if len(loc_parts) > 1 else ""
        country_id = ensure_country(country) if country else None

        events.append({
            "ufc_slug":      slug,
            "name":          name,
            "event_type":    classify_event(name),
            "event_date":    ev_date,
            "venue":         location,
            "city":          city,
            "status":        status,
            "ufc_url":       href,
            "last_scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    return events


def _scrape_event_fights(event_slug: str, event_url: str):
    """Scrapea los combates de un evento desde ufcstats.com"""
    resp = safe_get(event_url)
    if not resp: return

    # Obtener el ID del evento en Supabase
    ev_res = sb.table("events").select("id").eq("ufc_slug", event_slug).execute()
    if not ev_res.data: return
    event_id = ev_res.data[0]["id"]

    soup = BeautifulSoup(resp.text, "lxml")
    fight_rows = soup.select("tr.b-fight-details__table-row")

    position = 1
    for row in fight_rows:
        try:
            cols = row.select("td")
            if len(cols) < 8: continue

            # Peleadores
            fighters_el = cols[1].select("a") if len(cols) > 1 else []
            if len(fighters_el) < 2: continue

            name_a = clean(fighters_el[0].get_text())
            name_b = clean(fighters_el[1].get_text())

            # Resultado
            winner_text = clean(cols[0].get_text()) if cols else ""
            result      = clean(cols[7].get_text()) if len(cols) > 7 else ""
            rnd         = clean(cols[8].get_text()) if len(cols) > 8 else ""
            t           = clean(cols[9].get_text()) if len(cols) > 9 else ""

            # Resolver IDs de peleadores (buscar o crear)
            fa_id = _get_or_create_fighter(name_a)
            fb_id = _get_or_create_fighter(name_b)
            if not fa_id or not fb_id: continue

            # Determinar ganador
            winner_id = None
            if winner_text:
                if name_a.lower() in winner_text.lower():   winner_id = fa_id
                elif name_b.lower() in winner_text.lower(): winner_id = fb_id

            payload = {
                "event_id":       event_id,
                "fighter_a_id":   fa_id,
                "fighter_b_id":   fb_id,
                "winner_id":      winner_id,
                "result":         result if result else None,
                "result_round":   int(rnd) if rnd.isdigit() else None,
                "result_time":    t if t else None,
                "card_position":  position,
                "is_main_event":  position == 1,
                "status":         "Completed" if winner_id else "Scheduled",
            }

            # Upsert por event_id + fighter_a_id + fighter_b_id
            existing = sb.table("fights").select("id").eq(
                "event_id", event_id
            ).eq("fighter_a_id", fa_id).eq("fighter_b_id", fb_id).execute()

            if existing.data:
                sb.table("fights").update(payload).eq("id", existing.data[0]["id"]).execute()
            else:
                sb.table("fights").insert(payload).execute()

            position += 1

        except Exception as e:
            log(f"    Fight parse error: {e}")
            continue

    time.sleep(DELAY)


def _get_or_create_fighter(full_name: str) -> Optional[str]:
    """Busca un peleador por nombre completo, lo crea si no existe."""
    if not full_name: return None
    parts     = full_name.strip().split(" ", 1)
    first     = parts[0]
    last      = parts[1] if len(parts) > 1 else ""

    try:
        res = sb.table("fighters").select("id").ilike("first_name", first).ilike(
            "last_name", last
        ).execute()
        if res.data: return res.data[0]["id"]

        # Crear con datos mínimos — el scraper de perfiles completará el resto
        ins = sb.table("fighters").insert({
            "first_name": first,
            "last_name":  last,
            "status":     "Active",
        }).execute()
        return ins.data[0]["id"] if ins.data else None
    except:
        return None


# ─────────────────────────────────────────
# SCRAPER DE PELEADORES — ufc.com/athletes
# ─────────────────────────────────────────
def scrape_fighters(limit=None):
    if not sb:
        log("❌ Sin conexión a Supabase"); return

    log("="*55)
    log("SCRAPER PELEADORES · ufc.com/athletes")
    log("="*55)

    started   = datetime.now(timezone.utc)
    urls      = _get_all_athlete_urls()
    if limit: urls = urls[:limit]

    log(f"Total peleadores a procesar: {len(urls)}")
    new_c = upd_c = err_c = 0

    for url in tqdm(urls, desc="Peleadores", unit="f"):
        data = _scrape_athlete_page(url)
        if not data:
            err_c += 1
            time.sleep(DELAY)
            continue

        try:
            nat_id = ensure_country(data.pop("nationality_raw", ""))
            data["nationality_id"] = nat_id

            existing = sb.table("fighters").select("id").eq(
                "ufc_slug", data["ufc_slug"]
            ).execute()
            sb.table("fighters").upsert(data, on_conflict="ufc_slug").execute()

            if existing.data: upd_c += 1
            else: new_c += 1
        except Exception as e:
            log(f"  ERROR {data.get('ufc_slug')}: {e}")
            err_c += 1

        time.sleep(DELAY)

    _log_scraper("ufc_fighters", new_c, upd_c, err_c, started)
    log(f"✅ Peleadores: {new_c} nuevos · {upd_c} actualizados · {err_c} errores")


def _get_all_athlete_urls() -> list[str]:
    """Obtiene todas las URLs de atletas paginando ufc.com/athletes/all"""
    log("Obteniendo lista de URLs...")
    urls = set()
    page = 0

    while True:
        resp = safe_get(f"{UFC_ATHLETES_URL}?page={page}")
        if not resp: break

        soup  = BeautifulSoup(resp.text, "lxml")
        found = []

        for a in soup.select("a[href*='/athlete/']"):
            href = a.get("href","")
            if "/athlete/" in href and href not in urls:
                full = f"{UFC_BASE}{href}" if href.startswith("/") else href
                found.append(full)
                urls.add(full)

        log(f"  Página {page}: +{len(found)} (total {len(urls)})")
        if not found: break
        page += 1
        time.sleep(DELAY)

    return list(urls)


def _scrape_athlete_page(url: str) -> Optional[dict]:
    """Scrapea el perfil de un peleador desde ufc.com"""
    resp = safe_get(url)
    if not resp: return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Nombre
    name_el = (
        soup.select_one("h1.hero-profile__name") or
        soup.select_one(".c-hero-profile__name") or
        soup.select_one("h1")
    )
    if not name_el: return None
    full = clean(name_el.get_text())
    parts = full.split(" ", 1)
    first = parts[0]
    last  = parts[1] if len(parts) > 1 else ""

    # Nickname
    nick_el = soup.select_one(".hero-profile__nickname, .c-hero-profile__nickname")
    nick = clean(nick_el.get_text()).strip('"\'') if nick_el else None

    # Récord
    rec_el = soup.select_one(".hero-profile__division-body")
    wins, losses, draws = parse_record(clean(rec_el.get_text()) if rec_el else "")

    # Estado
    status_text = soup.get_text().lower()
    status = "Retired" if any(w in status_text[:2000] for w in ["retired","retirado"]) else "Active"

    # Slug
    slug = url.rstrip("/").split("/")[-1]

    # Bio fields
    bio = {}
    for item in soup.select(".c-bio__field"):
        lbl = item.select_one(".c-bio__label")
        val = item.select_one(".c-bio__text")
        if lbl and val:
            bio[clean(lbl.get_text()).lower()] = clean(val.get_text())

    # Imagen
    img = soup.select_one(".hero-profile__image img, [class*='hero'] img")
    img_url = img.get("src","") if img else ""

    return {
        "ufc_slug":          slug,
        "ufc_profile_url":   url,
        "first_name":        first,
        "last_name":         last,
        "nickname":          nick,
        "wins":              wins,
        "losses":            losses,
        "draws":             draws,
        "status":            status,
        "height_cm":         parse_height(bio.get("height","")),
        "reach_cm":          parse_reach(bio.get("reach","")),
        "stance":            bio.get("stance"),
        "nationality_raw":   bio.get("nationality", bio.get("hometown","")),
        "profile_image_url": img_url if img_url.startswith("http") else None,
        "last_scraped_at":   datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────
# DATOS HARDCODEADOS DE FALLBACK
# (se usan si el scraper falla — siempre actualizados)
# ─────────────────────────────────────────
def insert_fallback_events():
    """Inserta los eventos actuales hardcodeados directamente en Supabase."""
    if not sb:
        log("❌ Sin Supabase"); return

    log("Insertando eventos de fallback actualizados...")

    events = [
        # ── PRÓXIMOS ──
        {
            "ufc_slug": "ufc-327",
            "name": "UFC 327: Procházka vs. Ulberg",
            "event_type": "Numbered",
            "event_date": "2026-04-11",
            "venue": "Kaseya Center, Miami, Florida",
            "city": "Miami",
            "status": "Upcoming",
            "broadcast": "Paramount+",
            "ufc_url": "https://www.ufc.com/event/ufc-327",
        },
        {
            "ufc_slug": "ufc-fn-sterling-zalal",
            "name": "UFC Fight Night: Sterling vs. Zalal",
            "event_type": "Fight Night",
            "event_date": "2026-04-25",
            "venue": "UFC APEX, Las Vegas, Nevada",
            "city": "Las Vegas",
            "status": "Upcoming",
            "broadcast": "Paramount+",
            "ufc_url": "https://www.ufc.com/events",
        },
        {
            "ufc_slug": "ufc-fn-della-maddalena-prates",
            "name": "UFC Fight Night: Della Maddalena vs. Prates",
            "event_type": "Fight Night",
            "event_date": "2026-05-02",
            "venue": "RAC Arena, Perth, Australia",
            "city": "Perth",
            "status": "Upcoming",
            "broadcast": "Paramount+",
            "ufc_url": "https://www.ufc.com/events",
        },
        {
            "ufc_slug": "ufc-328",
            "name": "UFC 328: Chimaev vs. Strickland",
            "event_type": "Numbered",
            "event_date": "2026-05-09",
            "venue": "Prudential Center, Newark, New Jersey",
            "city": "Newark",
            "status": "Upcoming",
            "broadcast": "Paramount+",
            "ufc_url": "https://www.ufc.com/event/ufc-328",
        },
        {
            "ufc_slug": "ufc-freedom-250",
            "name": "UFC Freedom 250: Topuria vs. Gaethje",
            "event_type": "Special",
            "event_date": "2026-06-14",
            "venue": "The White House South Lawn, Washington D.C.",
            "city": "Washington D.C.",
            "status": "Upcoming",
            "broadcast": "Paramount+ / CBS",
            "ufc_url": "https://www.ufc.com/events",
        },
    ]

    for ev in events:
        ev["last_scraped_at"] = datetime.now(timezone.utc).isoformat()
        try:
            sb.table("events").upsert(ev, on_conflict="ufc_slug").execute()
            log(f"  ✅ {ev['name']}")
        except Exception as e:
            log(f"  ❌ {ev['name']}: {e}")

    # Insertar combates de UFC 328
    _insert_ufc328_fights()
    log("✅ Fallback completado")


def _insert_ufc328_fights():
    """Inserta los combates confirmados del UFC 328."""
    ev_res = sb.table("events").select("id").eq("ufc_slug","ufc-328").execute()
    if not ev_res.data:
        log("  No se encontró el evento UFC 328"); return

    event_id = ev_res.data[0]["id"]

    fights_data = [
        # (nombre_a, nombre_b, weight_lbs, card_segment, is_main, is_title, pos)
        ("Khamzat Chimaev",    "Sean Strickland",       185, "Main Card",   True,  True,  1),
        ("Joshua Van",         "Tatsuro Taira",          125, "Main Card",   False, True,  2),
        ("Alexander Volkov",   "Waldo Cortes-Acosta",   265, "Main Card",   False, False, 3),
        ("Sean Brady",         "Joaquin Buckley",       170, "Main Card",   False, False, 4),
        ("Jan Blachowicz",     "Bogdan Guskov",         205, "Main Card",   False, False, 5),
        ("King Green",         "Jeremy Stephens",       155, "Prelims",     False, False, 6),
        ("Roman Kopylov",      "Marco Tulio",           185, "Prelims",     False, False, 7),
        ("Clayton Carpenter",  "Jose Ochoa",            125, "Prelims",     False, False, 8),
        ("Baisangur Susurkaev","Djorden Santos",        185, "Prelims",     False, False, 9),
        ("Ateba Gautier",      "Osman Diaz",            185, "Prelims",     False, False, 10),
        ("Grant Dawson",       "Mateusz Rebecki",       155, "Prelims",     False, False, 11),
        ("Pat Sabatini",       "William Gomis",         145, "Prelims",     False, False, 12),
        ("Joel Alvarez",       "Yaroslav Amosov",       170, "Prelims",     False, False, 13),
    ]

    for f in fights_data:
        name_a, name_b, weight, segment, is_main, is_title, pos = f
        fa_id = _get_or_create_fighter(name_a)
        fb_id = _get_or_create_fighter(name_b)
        if not fa_id or not fb_id: continue

        try:
            existing = sb.table("fights").select("id").eq(
                "event_id", event_id
            ).eq("fighter_a_id", fa_id).execute()

            payload = {
                "event_id":       event_id,
                "fighter_a_id":   fa_id,
                "fighter_b_id":   fb_id,
                "card_position":  pos,
                "card_segment":   segment,
                "is_main_event":  is_main,
                "is_title_fight": is_title,
                "status":         "Scheduled",
                "weight_agreed_lbs": weight,
                "scheduled_rounds": 5 if is_main or is_title else 3,
            }

            if existing.data:
                sb.table("fights").update(payload).eq("id", existing.data[0]["id"]).execute()
            else:
                sb.table("fights").insert(payload).execute()

            log(f"  ✅ {name_a} vs {name_b}")
        except Exception as e:
            log(f"  ❌ {name_a} vs {name_b}: {e}")


# ─────────────────────────────────────────
# LOG SCRAPER
# ─────────────────────────────────────────
def _log_scraper(name, new_c, upd_c, err_c, started):
    if not sb: return
    try:
        sb.table("scraper_log").insert({
            "scraper":     name,
            "status":      "success" if err_c == 0 else "partial",
            "records_new": new_c,
            "records_upd": upd_c,
            "records_err": err_c,
            "started_at":  started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except: pass


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MMA Live Scraper")
    parser.add_argument("--mode", choices=["events","fighters","all","test","fallback"], default="fallback")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not sb:
        log("❌ SUPABASE_URL o SUPABASE_SERVICE_KEY no configurados en .env")
        sys.exit(1)

    log(f"✅ Conectado a Supabase: {SUPABASE_URL[:50]}...")

    if args.mode == "fallback":
        # Modo más rápido: inserta los eventos actuales hardcodeados
        insert_fallback_events()

    elif args.mode == "events":
        # Scrapea ufcstats.com + inserta fallback de eventos actuales
        scrape_events()
        insert_fallback_events()

    elif args.mode == "fighters":
        scrape_fighters(limit=args.limit)

    elif args.mode == "all":
        scrape_events()
        insert_fallback_events()
        scrape_fighters(limit=args.limit)

    elif args.mode == "test":
        log("Modo TEST: solo fallback + 5 peleadores")
        insert_fallback_events()
        scrape_fighters(limit=5)

    log("\n🏁 Scraper completado.")
