"""
MMA Live · API Backend (FastAPI)
Compatible con supabase==1.2.0 (sin compilación Rust)
"""

import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

load_dotenv()

# ─────────────────────────────────────────
# APP
# ─────────────────────────────────────────
app = FastAPI(
    title="MMA Live API",
    description="Backend para la PWA de MMA / UFC",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # En producción pon tu dominio exacto
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────
SUPABASE_URL     = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY     = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SVC_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

def get_sb() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_sb_admin() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SVC_KEY)


# ─────────────────────────────────────────
# AUTH — compatible con supabase-py 1.2.0
# ─────────────────────────────────────────
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")
    token = authorization.split(" ")[1]
    try:
        sb = get_sb()
        user_resp = sb.auth.api.get_user(token)
        if not user_resp or not user_resp.user:
            raise HTTPException(status_code=401, detail="Token inválido")
        return user_resp.user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")


async def get_optional_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        return None
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None


# ─────────────────────────────────────────
# MODELOS
# ─────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UpdateProfileRequest(BaseModel):
    username:     Optional[str] = None
    display_name: Optional[str] = None
    bio:          Optional[str] = None

class PredictionRequest(BaseModel):
    fight_id:            str
    predicted_winner_id: str
    predicted_method:    Optional[str] = None
    predicted_round:     Optional[int] = None
    confidence:          Optional[int] = None


# ─────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "MMA Live API", "version": "1.0.0"}

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────
@app.post("/auth/register", tags=["Auth"])
async def register(body: RegisterRequest):
    sb = get_sb()
    try:
        res = sb.auth.sign_up(email=body.email, password=body.password)
        if res.user:
            if body.username:
                get_sb_admin().table("user_profiles").update(
                    {"username": body.username}
                ).eq("id", str(res.user.id)).execute()
            return {
                "message": "Usuario registrado. Revisa tu email para confirmar.",
                "user_id": str(res.user.id),
            }
        raise HTTPException(status_code=400, detail="Error en el registro")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login", tags=["Auth"])
async def login(body: LoginRequest):
    sb = get_sb()
    try:
        res = sb.auth.sign_in(email=body.email, password=body.password)
        if res.user and res.session:
            profile = sb.table("user_profiles").select("*").eq(
                "id", str(res.user.id)
            ).execute()
            return {
                "access_token":  res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "expires_in":    res.session.expires_in,
                "user": {
                    "id":      str(res.user.id),
                    "email":   res.user.email,
                    "profile": profile.data[0] if profile.data else {},
                }
            }
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/logout", tags=["Auth"])
async def logout(user=Depends(get_current_user)):
    sb = get_sb()
    sb.auth.sign_out()
    return {"message": "Sesión cerrada"}


@app.post("/auth/refresh", tags=["Auth"])
async def refresh_token(refresh_token: str):
    sb = get_sb()
    try:
        res = sb.auth.api.refresh_access_token(refresh_token)
        return {
            "access_token":  res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "expires_in":    res.session.expires_in,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─────────────────────────────────────────
# PERFIL DE USUARIO
# ─────────────────────────────────────────
@app.get("/users/me", tags=["Users"])
async def get_my_profile(user=Depends(get_current_user)):
    sb = get_sb()
    res = sb.table("user_profiles").select(
        "*, countries(name,flag_emoji)"
    ).eq("id", str(user.id)).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return res.data[0]


@app.patch("/users/me", tags=["Users"])
async def update_my_profile(body: UpdateProfileRequest, user=Depends(get_current_user)):
    sb = get_sb()
    update_data = {k: v for k, v in body.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    res = sb.table("user_profiles").update(update_data).eq(
        "id", str(user.id)
    ).execute()
    return res.data[0] if res.data else {"message": "Actualizado"}


@app.get("/users/me/favorites", tags=["Users"])
async def get_my_favorites(user=Depends(get_current_user)):
    sb = get_sb()
    res = sb.table("user_favorite_fighters").select(
        "*, fighters(id, first_name, last_name, nickname, status, "
        "wins, losses, draws, profile_image_url)"
    ).eq("user_id", str(user.id)).execute()
    return res.data


@app.post("/users/me/favorites/{fighter_id}", tags=["Users"])
async def add_favorite(fighter_id: str, user=Depends(get_current_user)):
    sb = get_sb()
    try:
        sb.table("user_favorite_fighters").insert({
            "user_id":    str(user.id),
            "fighter_id": fighter_id,
        }).execute()
        return {"message": "Añadido a favoritos"}
    except Exception:
        raise HTTPException(status_code=409, detail="Ya está en favoritos")


@app.delete("/users/me/favorites/{fighter_id}", tags=["Users"])
async def remove_favorite(fighter_id: str, user=Depends(get_current_user)):
    sb = get_sb()
    sb.table("user_favorite_fighters").delete().eq(
        "user_id", str(user.id)
    ).eq("fighter_id", fighter_id).execute()
    return {"message": "Eliminado de favoritos"}


# ─────────────────────────────────────────
# PELEADORES
# ─────────────────────────────────────────
@app.get("/fighters", tags=["Fighters"])
async def list_fighters(
    search:       Optional[str] = Query(None),
    status:       Optional[str] = Query(None),
    weight_class: Optional[str] = Query(None),
    gender:       Optional[str] = Query(None),
    page:         int = Query(1, ge=1),
    per_page:     int = Query(20, ge=1, le=100),
):
    sb = get_sb()
    offset = (page - 1) * per_page

    query = sb.table("fighters").select(
        "id, first_name, last_name, nickname, status, gender, "
        "wins, losses, draws, ufc_slug, profile_image_url, "
        "nationality:countries!nationality_id(name, flag_emoji), "
        "weight_class:weight_classes!primary_weight_class_id(name, name_es)",
        count="exact"
    )

    if search:
        query = query.ilike("last_name", f"%{search}%")
    if status:
        query = query.eq("status", status)
    if gender:
        query = query.eq("gender", gender)

    query = query.order("last_name").range(offset, offset + per_page - 1)
    res = query.execute()

    return {
        "data":        res.data,
        "total":       res.count,
        "page":        page,
        "per_page":    per_page,
        "total_pages": -(-res.count // per_page) if res.count else 0,
    }


@app.get("/fighters/{slug}", tags=["Fighters"])
async def get_fighter(slug: str, user=Depends(get_optional_user)):
    sb = get_sb()

    fighter_res = sb.table("fighters").select(
        "*, "
        "nationality:countries!nationality_id(name, flag_emoji, code), "
        "weight_class:weight_classes!primary_weight_class_id(name, name_es, weight_limit_lbs)"
    ).eq("ufc_slug", slug).execute()

    if not fighter_res.data:
        raise HTTPException(status_code=404, detail="Peleador no encontrado")

    fighter = fighter_res.data[0]

    # Historial de combates
    fights_res = sb.table("fighter_fight_history").select("*").or_(
        f"fighter_a_id.eq.{fighter['id']},fighter_b_id.eq.{fighter['id']}"
    ).execute()

    # Rankings
    rankings_res = sb.table("rankings").select(
        "rank_position, rank_date, weight_class:weight_classes(name_es)"
    ).eq("fighter_id", fighter["id"]).order("rank_date", desc=True).limit(5).execute()

    # Favorito del usuario
    is_favorite = False
    if user:
        fav_res = sb.table("user_favorite_fighters").select("user_id").eq(
            "user_id", str(user.id)
        ).eq("fighter_id", fighter["id"]).execute()
        is_favorite = bool(fav_res.data)

    return {
        **fighter,
        "fight_history": fights_res.data,
        "rankings":      rankings_res.data,
        "is_favorite":   is_favorite,
    }


# ─────────────────────────────────────────
# EVENTOS
# ─────────────────────────────────────────
@app.get("/events", tags=["Events"])
async def list_events(
    status:   Optional[str] = Query(None),
    page:     int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
):
    sb = get_sb()
    offset = (page - 1) * per_page
    query = sb.table("events").select(
        "*, country:countries(name, flag_emoji)", count="exact"
    )
    if status:
        query = query.eq("status", status)
    query = query.order("event_date", desc=(status == "Completed")).range(
        offset, offset + per_page - 1
    )
    res = query.execute()
    return {"data": res.data, "total": res.count, "page": page, "per_page": per_page}


@app.get("/events/upcoming", tags=["Events"])
async def upcoming_events():
    sb = get_sb()
    res = sb.table("upcoming_events_with_fights").select("*").execute()
    return res.data


@app.get("/events/{slug}", tags=["Events"])
async def get_event(slug: str):
    sb = get_sb()
    event_res = sb.table("events").select(
        "*, country:countries(name, flag_emoji)"
    ).eq("ufc_slug", slug).execute()

    if not event_res.data:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    event = event_res.data[0]

    fights_res = sb.table("fights").select(
        "*, "
        "fighter_a:fighters!fighter_a_id(id, first_name, last_name, nickname, "
        "  wins, losses, draws, profile_image_url, "
        "  nationality:countries!nationality_id(flag_emoji)), "
        "fighter_b:fighters!fighter_b_id(id, first_name, last_name, nickname, "
        "  wins, losses, draws, profile_image_url, "
        "  nationality:countries!nationality_id(flag_emoji)), "
        "winner:fighters!winner_id(id, first_name, last_name), "
        "weight_class:weight_classes(name, name_es)"
    ).eq("event_id", event["id"]).order("card_position").execute()

    return {**event, "fights": fights_res.data}


# ─────────────────────────────────────────
# PREDICCIONES
# ─────────────────────────────────────────
@app.get("/fights/{fight_id}/predictions/stats", tags=["Predictions"])
async def fight_prediction_stats(fight_id: str):
    sb = get_sb()
    res = sb.table("user_predictions").select(
        "predicted_winner_id"
    ).eq("fight_id", fight_id).execute()

    if not res.data:
        return {"total": 0, "breakdown": {}}

    from collections import Counter
    counts = Counter(p["predicted_winner_id"] for p in res.data)
    total  = len(res.data)
    return {
        "total":     total,
        "breakdown": {k: {"count": v, "pct": round(v/total*100, 1)} for k, v in counts.items()},
    }


@app.post("/fights/{fight_id}/predictions", tags=["Predictions"])
async def create_prediction(
    fight_id: str,
    body: PredictionRequest,
    user=Depends(get_current_user)
):
    sb = get_sb()
    fight = sb.table("fights").select("status").eq("id", fight_id).execute()
    if not fight.data:
        raise HTTPException(status_code=404, detail="Combate no encontrado")
    if fight.data[0]["status"] != "Scheduled":
        raise HTTPException(status_code=400, detail="El combate ya no acepta predicciones")

    try:
        res = sb.table("user_predictions").insert({
            "user_id":             str(user.id),
            "fight_id":            fight_id,
            "predicted_winner_id": body.predicted_winner_id,
            "predicted_method":    body.predicted_method,
            "predicted_round":     body.predicted_round,
            "confidence":          body.confidence,
        }).execute()
        return {"message": "Predicción guardada", "prediction": res.data[0]}
    except Exception:
        raise HTTPException(status_code=409, detail="Ya tienes una predicción para este combate")


@app.get("/users/me/predictions", tags=["Predictions"])
async def my_predictions(user=Depends(get_current_user)):
    sb = get_sb()
    res = sb.table("user_predictions").select(
        "*, fight:fights(*, event:events(name, event_date), "
        "fighter_a:fighters!fighter_a_id(first_name, last_name), "
        "fighter_b:fighters!fighter_b_id(first_name, last_name))"
    ).eq("user_id", str(user.id)).order("created_at", desc=True).execute()
    return res.data


# ─────────────────────────────────────────
# RANKINGS
# ─────────────────────────────────────────
@app.get("/rankings", tags=["Rankings"])
async def all_rankings():
    sb = get_sb()
    res = sb.table("current_rankings").select("*").order("weight_class").order(
        "rank_position"
    ).execute()
    return res.data


@app.get("/rankings/{weight_class_name}", tags=["Rankings"])
async def get_rankings(weight_class_name: str):
    sb = get_sb()
    res = sb.table("current_rankings").select("*").eq(
        "weight_class", weight_class_name
    ).order("rank_position").execute()
    return res.data
