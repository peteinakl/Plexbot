from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import APP_NAME, APP_VERSION, FRONTEND_DIST_DIR
from .db import (
    db_session,
    get_all_settings,
    get_setting,
    hydrate_media_row,
    init_db,
    set_settings_bulk,
)
from .llm_curator import (
    DEFAULT_MODELS,
    curate_with_llm,
    generate_taste_portrait,
    get_active_llm_config,
    test_llm_connection,
)
from .plex_client import (
    SYNC_STATE,
    build_plex_deep_link,
    check_pin_login,
    discover_and_probe_servers,
    fetch_outside_discover_candidates,
    fetch_poster_bytes,
    start_pin_login,
    sync_all_servers,
    toggle_plex_watchlist,
    verify_and_store_plex_token,
)
from .recommender import ENGINE, MOOD_DEFINITIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("plexbot.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TokenLoginRequest(BaseModel):
    token: str


class PinStartRequest(BaseModel):
    forward_url: str | None = None


class ServerToggleRequest(BaseModel):
    enabled: bool


class ProfileCreateRequest(BaseModel):
    name: str
    icon: str = "user"
    description: str = ""
    inherit_shared_history: bool = True


class FeedbackRequest(BaseModel):
    profile_id: str = "together"
    media_id: int
    sentiment: str  # love | like | meh | dislike | dismiss | seen_unrated | clear


class WatchlistToggleRequest(BaseModel):
    on_watchlist: bool


class LLMSettingsRequest(BaseModel):
    llm_provider: str
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_model: str | None = None
    anthropic_model: str | None = None
    openai_model: str | None = None


class LLMTestRequest(BaseModel):
    provider: str
    api_key: str | None = None
    model: str | None = None


class AICurateRequest(BaseModel):
    profile_id: str = "together"
    mood: str = "all"
    media_type: str = "all"
    source_scope: str = "plex_all"
    include_outside: bool = False
    discovery_level: float = 0.35
    max_duration: int | None = None
    decade: str | None = None
    prompt: str = ""
    exclude_watchlist: bool = False
    force_refresh: bool = False


class PortraitRequest(BaseModel):
    profile_id: str = "together"
    force_refresh: bool = False


def _mask_key(raw: str) -> str:
    if not raw or len(raw) < 8:
        return ""
    return f"{raw[:4]}••••{raw[-4:]}"


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    s = get_all_settings()
    plex_token = s.get("plex_token", "")
    llm_cfg = get_active_llm_config()

    with db_session() as conn:
        profiles = [dict(r) for r in conn.execute("SELECT * FROM profiles ORDER BY created_at ASC").fetchall()]
        servers = [
            {
                "machine_id": r["machine_id"],
                "name": r["name"],
                "owned": bool(r["owned"]),
                "owner_name": r["owner_name"],
                "is_local_conn": bool(r["is_local_conn"]),
                "is_relay": bool(r["is_relay"]),
                "latency_ms": r["latency_ms"],
                "online": bool(r["online"]),
                "enabled": bool(r["enabled"]),
                "movie_count": r["movie_count"],
                "show_count": r["show_count"],
                "last_synced_at": r["last_synced_at"],
            }
            for r in conn.execute("SELECT * FROM servers ORDER BY owned DESC, name ASC").fetchall()
        ]
        stats_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_items,
                SUM(CASE WHEN media_type = 'movie' AND is_external_only = 0 THEN 1 ELSE 0 END) AS total_movies,
                SUM(CASE WHEN media_type = 'show' AND is_external_only = 0 THEN 1 ELSE 0 END) AS total_shows,
                SUM(CASE WHEN is_watched = 1 THEN 1 ELSE 0 END) AS watched_count,
                SUM(CASE WHEN on_watchlist = 1 THEN 1 ELSE 0 END) AS watchlist_count
            FROM media_items
            """
        ).fetchone()
        feedback_count = conn.execute("SELECT COUNT(*) AS c FROM taste_feedback").fetchone()["c"]

    return {
        "authenticated": bool(plex_token),
        "user": {
            "username": s.get("plex_username", ""),
            "email": s.get("plex_email", ""),
            "thumb": s.get("plex_thumb", ""),
        }
        if plex_token
        else None,
        "last_sync_at": int(s["last_sync_at"]) if s.get("last_sync_at") else None,
        "sync": SYNC_STATE.to_dict(),
        "profiles": profiles,
        "servers": servers,
        "stats": {
            "total_items": int(stats_row["total_items"] or 0),
            "total_movies": int(stats_row["total_movies"] or 0),
            "total_shows": int(stats_row["total_shows"] or 0),
            "watched_count": int(stats_row["watched_count"] or 0),
            "watchlist_count": int(stats_row["watchlist_count"] or 0),
            "feedback_count": int(feedback_count or 0),
        },
        "llm": {
            "enabled": llm_cfg["enabled"],
            "provider": s.get("llm_provider", "none"),
            "active_model": llm_cfg["model"],
            "has_gemini_key": bool(s.get("gemini_api_key")),
            "has_anthropic_key": bool(s.get("anthropic_api_key")),
            "has_openai_key": bool(s.get("openai_api_key")),
            "gemini_key_masked": _mask_key(s.get("gemini_api_key", "")),
            "anthropic_key_masked": _mask_key(s.get("anthropic_api_key", "")),
            "openai_key_masked": _mask_key(s.get("openai_api_key", "")),
            "gemini_model": s.get("gemini_model") or DEFAULT_MODELS["gemini"],
            "anthropic_model": s.get("anthropic_model") or DEFAULT_MODELS["anthropic"],
            "openai_model": s.get("openai_model") or DEFAULT_MODELS["openai"],
        },
        "moods": [
            {"id": "all", "label": "All Moods"},
            *[{"id": k, "label": v["label"]} for k, v in MOOD_DEFINITIONS.items()],
        ],
    }


@app.post("/api/auth/plex/pin")
async def api_plex_pin_start(req: PinStartRequest) -> dict[str, Any]:
    try:
        return await start_pin_login(forward_url=req.forward_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not start Plex sign-in: {exc}") from exc


@app.get("/api/auth/plex/pin/{pin_id}")
async def api_plex_pin_check(pin_id: int, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        res = await check_pin_login(pin_id)
        if res.get("authenticated") and not SYNC_STATE.running:
            background_tasks.add_task(sync_all_servers)
        return res
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/auth/plex/token")
async def api_plex_token_login(req: TokenLoginRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        user = await verify_and_store_plex_token(req.token)
        if not SYNC_STATE.running:
            background_tasks.add_task(sync_all_servers)
        return {"authenticated": True, "user": user}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Plex token: {exc}") from exc


@app.post("/api/auth/plex/logout")
async def api_plex_logout() -> dict[str, Any]:
    set_settings_bulk({"plex_token": "", "plex_username": "", "plex_email": "", "plex_thumb": ""})
    return {"ok": True}


@app.post("/api/sync")
async def api_trigger_sync(background_tasks: BackgroundTasks) -> dict[str, Any]:
    if not get_setting("plex_token"):
        raise HTTPException(status_code=401, detail="Sign into Plex first.")
    if not SYNC_STATE.running:
        background_tasks.add_task(sync_all_servers)
        await asyncio.sleep(0.05)
    return SYNC_STATE.to_dict()


@app.get("/api/sync/status")
async def api_sync_status() -> dict[str, Any]:
    return SYNC_STATE.to_dict()


@app.post("/api/servers/refresh")
async def api_refresh_servers() -> dict[str, Any]:
    servers = await discover_and_probe_servers()
    return {"servers": servers}


@app.post("/api/servers/{machine_id}/toggle")
async def api_toggle_server(machine_id: str, req: ServerToggleRequest) -> dict[str, Any]:
    with db_session() as conn:
        conn.execute(
            "UPDATE servers SET enabled = ? WHERE machine_id = ?",
            (1 if req.enabled else 0, machine_id),
        )
    return {"machine_id": machine_id, "enabled": req.enabled}


@app.post("/api/profiles")
async def api_create_profile(req: ProfileCreateRequest) -> dict[str, Any]:
    clean_name = req.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Profile name is required.")
    slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-") or "viewer"
    pid = f"{slug}-{int(time.time()) % 10000}"
    now = int(time.time())
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO profiles (id, name, icon, description, inherit_shared_history, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pid, clean_name, req.icon, req.description, 1 if req.inherit_shared_history else 0, now),
        )
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (pid,)).fetchone()
    return dict(row)


@app.delete("/api/profiles/{profile_id}")
async def api_delete_profile(profile_id: str) -> dict[str, Any]:
    if profile_id in ("together", "me", "partner"):
        raise HTTPException(status_code=400, detail="Built-in household profiles cannot be deleted.")
    with db_session() as conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    return {"deleted": profile_id}


@app.get("/api/recommendations")
async def api_get_recommendations(
    profile_id: str = Query("together"),
    mood: str = Query("all"),
    media_type: str = Query("all"),
    source_scope: str = Query("plex_all"),
    include_outside: bool = Query(False),
    discovery_level: float = Query(0.35),
    max_duration: int | None = Query(None),
    decade: str | None = Query(None),
    prompt: str = Query(""),
    exclude_watchlist: bool = Query(False),
    limit: int = Query(36, ge=4, le=100),
) -> dict[str, Any]:
    # If user toggled include_outside ON and we don't yet have many external Discover items cached,
    # opportunistically seed related works from Plex's global metadata catalog!
    if include_outside and get_setting("plex_token"):
        with db_session() as conn:
            ext_cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE is_external_only = 1"
            ).fetchone()["c"]
        if int(ext_cnt or 0) < 12:
            pre_ctx = ENGINE.load_context()
            pre_taste = ENGINE.build_profile_taste(pre_ctx, profile_id=profile_id)
            seed_rks = [
                str(a["discover_rating_key"])
                for a in pre_taste["dna"].get("anchor_favorites", [])
                if a.get("discover_rating_key")
            ]
            if seed_rks:
                try:
                    await fetch_outside_discover_candidates(
                        seed_rks, media_type_filter=media_type, limit=16
                    )
                except Exception as exc:
                    logger.warning("Outside discovery fetch warning: %s", exc)

    return ENGINE.recommend(
        profile_id=profile_id,
        mood=mood,
        media_type=media_type,
        source_scope=source_scope,
        include_outside=include_outside,
        discovery_level=discovery_level,
        max_duration=max_duration,
        decade=decade,
        prompt=prompt,
        exclude_watchlist=exclude_watchlist,
        limit=limit,
    )


@app.post("/api/recommendations/ai-curate")
async def api_ai_curate(req: AICurateRequest) -> dict[str, Any]:
    base = ENGINE.recommend(
        profile_id=req.profile_id,
        mood=req.mood,
        media_type=req.media_type,
        source_scope=req.source_scope,
        include_outside=req.include_outside,
        discovery_level=req.discovery_level,
        max_duration=req.max_duration,
        decade=req.decade,
        prompt=req.prompt,
        exclude_watchlist=req.exclude_watchlist,
        limit=50,
    )
    if not base["items"] and not req.include_outside:
        return {
            "curator_headline": "No matching titles found for these exact filters.",
            "items": [],
            "dna": base["dna"],
        }

    try:
        curated = await curate_with_llm(
            base_recommendations=base["items"],
            dna=base["dna"],
            profile_name=base["profile"]["name"],
            profile_id=req.profile_id,
            mood=req.mood,
            prompt=req.prompt,
            include_outside=req.include_outside,
            discovery_level=req.discovery_level,
            media_type=req.media_type,
            force_refresh=req.force_refresh,
        )
        curated["dna"] = base["dna"]
        curated["total_pool"] = base["total_pool"]
        return curated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI curation error")
        raise HTTPException(status_code=502, detail=f"LLM curation error: {exc}") from exc


@app.post("/api/taste-portrait")
async def api_taste_portrait(req: PortraitRequest) -> dict[str, Any]:
    ctx = ENGINE.load_context()
    taste = ENGINE.build_profile_taste(ctx, profile_id=req.profile_id)
    if not taste["dna"]["anchor_favorites"]:
        raise HTTPException(
            status_code=400,
            detail="Sync your Plex watch history or rate a few titles first so Plexbot can read your taste.",
        )
    try:
        return await generate_taste_portrait(
            profile_id=req.profile_id,
            profile_name=taste["profile"]["name"],
            dna=taste["dna"],
            force_refresh=req.force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed generating taste portrait: {exc}") from exc


@app.get("/api/history")
async def api_get_history(
    profile_id: str = Query("together"),
    filter_mode: str = Query("all"),
    media_type: str = Query("all"),
    search: str = Query(""),
    limit: int = Query(120, ge=10, le=500),
) -> dict[str, Any]:
    return ENGINE.get_watch_history(
        profile_id=profile_id,
        filter_mode=filter_mode,
        media_type=media_type,
        search=search,
        limit=limit,
    )


@app.get("/api/catalog/search")
async def api_search_catalog(
    q: str = Query(""),
    profile_id: str = Query("together"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    term = q.strip()
    if not term:
        return {"items": []}

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM media_items
            WHERE title LIKE ? OR original_title LIKE ? OR directors_json LIKE ? OR cast_json LIKE ?
            ORDER BY is_external_only ASC, audience_rating DESC NULLS LAST
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        ).fetchall()

        fb_map = {
            int(r["media_id"]): r["sentiment"]
            for r in conn.execute(
                "SELECT media_id, sentiment FROM taste_feedback WHERE profile_id = ?",
                (profile_id,),
            ).fetchall()
        }

        items: list[dict[str, Any]] = []
        for r in rows:
            mid = int(r["id"])
            srcs = []
            for s in conn.execute(
                """
                SELECT ms.*, sv.name AS server_name, sv.owned, sv.owner_name, sv.online, sv.latency_ms
                FROM media_sources ms
                JOIN servers sv ON sv.machine_id = ms.machine_id
                WHERE ms.media_id = ? AND sv.enabled = 1
                """,
                (mid,),
            ).fetchall():
                sd = dict(s)
                sd["deep_link"] = build_plex_deep_link(sd["machine_id"], sd["rating_key"])
                srcs.append(sd)
            items.append(hydrate_media_row(r, sources=srcs, feedback_sentiment=fb_map.get(mid)))

    return {"items": items}


@app.post("/api/feedback")
async def api_set_feedback(req: FeedbackRequest) -> dict[str, Any]:
    valid = {"love", "like", "meh", "dislike", "dismiss", "seen_unrated", "clear"}
    if req.sentiment not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid sentiment: {req.sentiment}")

    now = int(time.time())
    with db_session() as conn:
        if req.sentiment == "clear":
            conn.execute(
                "DELETE FROM taste_feedback WHERE profile_id = ? AND media_id = ?",
                (req.profile_id, req.media_id),
            )
            current = None
        else:
            conn.execute(
                """
                INSERT OR REPLACE INTO taste_feedback (profile_id, media_id, sentiment, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (req.profile_id, req.media_id, req.sentiment, now),
            )
            current = req.sentiment
        # Invalidate cached LLM curations for this profile when taste feedback changes
        conn.execute("DELETE FROM llm_cache WHERE profile_id = ?", (req.profile_id,))

    return {"profile_id": req.profile_id, "media_id": req.media_id, "sentiment": current}


@app.post("/api/watchlist/{media_id}")
async def api_watchlist_toggle(media_id: int, req: WatchlistToggleRequest) -> dict[str, Any]:
    try:
        return await toggle_plex_watchlist(media_id, req.on_watchlist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Plex Watchlist error: {exc}") from exc


@app.post("/api/settings/llm")
async def api_save_llm_settings(req: LLMSettingsRequest) -> dict[str, Any]:
    updates: dict[str, str] = {"llm_provider": req.llm_provider}
    if req.gemini_api_key is not None and "•" not in req.gemini_api_key:
        updates["gemini_api_key"] = req.gemini_api_key.strip()
    if req.anthropic_api_key is not None and "•" not in req.anthropic_api_key:
        updates["anthropic_api_key"] = req.anthropic_api_key.strip()
    if req.openai_api_key is not None and "•" not in req.openai_api_key:
        updates["openai_api_key"] = req.openai_api_key.strip()
    if req.gemini_model:
        updates["gemini_model"] = req.gemini_model.strip()
    if req.anthropic_model:
        updates["anthropic_model"] = req.anthropic_model.strip()
    if req.openai_model:
        updates["openai_model"] = req.openai_model.strip()

    set_settings_bulk(updates)
    with db_session() as conn:
        conn.execute("DELETE FROM llm_cache")
    return {"ok": True, "llm": get_active_llm_config()}


@app.post("/api/settings/llm/test")
async def api_test_llm(req: LLMTestRequest) -> dict[str, Any]:
    s = get_all_settings()
    stored_key_map = {
        "gemini": s.get("gemini_api_key", ""),
        "anthropic": s.get("anthropic_api_key", ""),
        "openai": s.get("openai_api_key", ""),
    }
    key = req.api_key
    if not key or "•" in key:
        key = stored_key_map.get(req.provider, "")
    model = req.model or DEFAULT_MODELS.get(req.provider, "")
    try:
        return await test_llm_connection(req.provider, key, model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/poster/{media_id}")
async def api_poster(media_id: int) -> Response:
    res = await fetch_poster_bytes(media_id)
    if not res:
        raise HTTPException(status_code=404, detail="Poster unavailable")
    content, media_type = res
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


# Serve built frontend SPA when available
if (FRONTEND_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    target = FRONTEND_DIST_DIR / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(str(target))
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return Response(
        content="Plexbot backend is running. Build frontend (`cd frontend && npm run build`) to load UI.",
        media_type="text/plain",
    )
