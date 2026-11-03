from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from .config import APP_NAME, APP_VERSION, POSTER_CACHE_DIR, ensure_data_dirs
from .db import db_session, get_setting, set_setting, set_settings_bulk

logger = logging.getLogger("plexbot.plex")

PLEX_TV_BASE = "https://plex.tv"
PLEX_DISCOVER_BASE = "https://discover.provider.plex.tv"
PLEX_METADATA_BASE = "https://metadata.provider.plex.tv"


class SyncProgress:
    """Thread/async-safe observable sync state for live UI updates."""

    def __init__(self) -> None:
        self.running: bool = False
        self.phase: str = "idle"
        self.message: str = ""
        self.total_servers: int = 0
        self.completed_servers: int = 0
        self.items_indexed: int = 0
        self.servers_detail: dict[str, dict[str, Any]] = {}
        self.error: str | None = None
        self.started_at: int | None = None
        self.finished_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "message": self.message,
            "total_servers": self.total_servers,
            "completed_servers": self.completed_servers,
            "items_indexed": self.items_indexed,
            "servers_detail": list(self.servers_detail.values()),
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


SYNC_STATE = SyncProgress()
_ACTIVE_PINS: dict[int, dict[str, str]] = {}


def plex_headers(token: str | None = None, client_id: str | None = None) -> dict[str, str]:
    cid = client_id or get_setting("plex_client_id", "plexbot-local")
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": APP_VERSION,
        "X-Plex-Client-Identifier": cid,
        "X-Plex-Platform": "macOS" if platform.system() == "Darwin" else platform.system(),
        "X-Plex-Platform-Version": platform.release(),
        "X-Plex-Device": "Mac" if platform.system() == "Darwin" else "PC",
        "X-Plex-Device-Name": "Plexbot Taste Engine",
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


def normalize_title_key(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", (title or "").lower())
    return cleaned or "untitled"


def extract_canonical_identity(item: dict[str, Any], media_type: str) -> tuple[str, str | None, str | None, str | None, str | None]:
    """
    Returns (canonical_key, plex_guid, discover_rating_key, imdb_id, tmdb_id).
    Deduplicates identical titles across local + multiple friends' shared Plex servers.
    """
    raw_guid = str(item.get("guid") or "")
    plex_guid: str | None = None
    discover_rk: str | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None
    tvdb_id: str | None = None

    if raw_guid.startswith("plex://"):
        plex_guid = raw_guid
        parts = raw_guid.rsplit("/", 1)
        if len(parts) == 2 and parts[1]:
            discover_rk = parts[1]
    elif "imdb://" in raw_guid:
        m = re.search(r"(tt\d+)", raw_guid)
        if m:
            imdb_id = m.group(1)
    elif "themoviedb://" in raw_guid or "tmdb://" in raw_guid:
        m = re.search(r"(\d+)", raw_guid.split("://", 1)[-1])
        if m:
            tmdb_id = m.group(1)

    for g in item.get("Guid") or []:
        gid = str(g.get("id") or "")
        if gid.startswith("imdb://") and not imdb_id:
            imdb_id = gid.replace("imdb://", "").strip()
        elif gid.startswith("tmdb://") and not tmdb_id:
            tmdb_id = gid.replace("tmdb://", "").strip()
        elif gid.startswith("tvdb://") and not tvdb_id:
            tvdb_id = gid.replace("tvdb://", "").strip()

    if discover_rk:
        canonical = f"plex:{media_type}:{discover_rk}"
    elif imdb_id:
        canonical = f"imdb:{media_type}:{imdb_id}"
    elif tmdb_id:
        canonical = f"tmdb:{media_type}:{tmdb_id}"
    elif tvdb_id:
        canonical = f"tvdb:{media_type}:{tvdb_id}"
    else:
        yr = item.get("year") or 0
        canonical = f"title:{media_type}:{normalize_title_key(item.get('title', ''))}:{yr}"

    return canonical, plex_guid, discover_rk, imdb_id, tmdb_id


def parse_resolution(media_list: list[dict[str, Any]] | None) -> tuple[str, str, int]:
    if not media_list:
        return "", "", 0
    best_res = ""
    best_rank = -1
    codec = ""
    hdr = 0
    rank_map = {"4k": 4, "2160": 4, "1080": 3, "720": 2, "576": 1, "480": 1, "sd": 1}
    label_map = {"4k": "4K", "2160": "4K", "1080": "1080p", "720": "720p", "576": "SD", "480": "SD", "sd": "SD"}
    for m in media_list:
        vr = str(m.get("videoResolution") or "").lower()
        rk = rank_map.get(vr, 0)
        if rk > best_rank:
            best_rank = rk
            best_res = label_map.get(vr, vr.upper() if vr else "")
            codec = str(m.get("videoCodec") or "").upper()
        for part in m.get("Part") or []:
            for stream in part.get("Stream") or []:
                if stream.get("colorTrc") in ("smpte2084", "arib-std-b67") or stream.get("DOVIPresent"):
                    hdr = 1
    return best_res, codec, hdr


async def start_pin_login(forward_url: str | None = None) -> dict[str, Any]:
    client_id = get_setting("plex_client_id")
    headers = plex_headers(client_id=client_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{PLEX_TV_BASE}/api/v2/pins",
            headers=headers,
            params={"strong": "true"},
        )
        resp.raise_for_status()
        data = resp.json()

    pin_id = int(data["id"])
    code = str(data["code"])
    _ACTIVE_PINS[pin_id] = {"code": code, "client_id": client_id}

    oauth_params = {
        "clientID": headers["X-Plex-Client-Identifier"],
        "code": code,
        "context[device][product]": headers["X-Plex-Product"],
        "context[device][version]": headers["X-Plex-Version"],
        "context[device][platform]": headers["X-Plex-Platform"],
        "context[device][platformVersion]": headers["X-Plex-Platform-Version"],
        "context[device][device]": headers["X-Plex-Device"],
        "context[device][deviceName]": headers["X-Plex-Device-Name"],
    }
    if forward_url:
        oauth_params["forwardUrl"] = forward_url

    auth_url = f"https://app.plex.tv/auth#?{urlencode(oauth_params)}"
    return {"pin_id": pin_id, "code": code, "auth_url": auth_url}


async def check_pin_login(pin_id: int) -> dict[str, Any]:
    meta = _ACTIVE_PINS.get(pin_id, {})
    client_id = meta.get("client_id") or get_setting("plex_client_id")
    code = meta.get("code", "")
    headers = plex_headers(client_id=client_id)
    params = {"code": code} if code else {}

    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(
            f"{PLEX_TV_BASE}/api/v2/pins/{pin_id}",
            headers=headers,
            params=params,
        )
        if resp.status_code == 404:
            return {"authenticated": False, "expired": True}
        resp.raise_for_status()
        data = resp.json()

    auth_token = data.get("authToken")
    if not auth_token:
        return {"authenticated": False, "expired": False}

    user_info = await verify_and_store_plex_token(auth_token)
    _ACTIVE_PINS.pop(pin_id, None)
    return {"authenticated": True, "user": user_info}


async def verify_and_store_plex_token(token: str) -> dict[str, Any]:
    clean_token = token.strip()
    headers = plex_headers(token=clean_token)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{PLEX_TV_BASE}/api/v2/user", headers=headers)
        resp.raise_for_status()
        u = resp.json()

    username = u.get("username") or u.get("title") or "Plex User"
    email = u.get("email") or ""
    thumb = u.get("thumb") or ""
    set_settings_bulk(
        {
            "plex_token": clean_token,
            "plex_username": username,
            "plex_email": email,
            "plex_thumb": thumb,
        }
    )
    return {"username": username, "email": email, "thumb": thumb}


async def _probe_server_connection(
    client: httpx.AsyncClient,
    uri: str,
    access_token: str,
    is_local: bool,
    is_relay: bool,
) -> dict[str, Any] | None:
    t0 = time.perf_counter()
    try:
        resp = await client.get(
            f"{uri.rstrip('/')}/library/sections",
            headers=plex_headers(token=access_token),
            timeout=4.5,
        )
        if resp.status_code != 200:
            return None
        latency_ms = int((time.perf_counter() - t0) * 1000)
        payload = resp.json()
        sections = payload.get("MediaContainer", {}).get("Directory", [])
        return {
            "uri": uri.rstrip("/"),
            "latency_ms": latency_ms,
            "is_local": is_local,
            "is_relay": is_relay,
            "sections": sections,
        }
    except Exception:
        return None


async def discover_and_probe_servers(token: str | None = None) -> list[dict[str, Any]]:
    plex_token = token or get_setting("plex_token")
    if not plex_token:
        return []

    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=15.0) as client:
        resp = await client.get(
            f"{PLEX_TV_BASE}/api/v2/resources",
            headers=plex_headers(token=plex_token),
            params={"includeHttps": "1", "includeRelay": "1", "includeIPv6": "0"},
        )
        resp.raise_for_status()
        resources = resp.json()

        server_resources = [
            r for r in resources if "server" in str(r.get("provides") or "").split(",")
        ]

        # Preserve existing enabled states
        existing_enabled: dict[str, int] = {}
        with db_session() as conn:
            for row in conn.execute("SELECT machine_id, enabled FROM servers").fetchall():
                existing_enabled[row["machine_id"]] = int(row["enabled"])

        async def resolve_resource(res: dict[str, Any]) -> dict[str, Any]:
            machine_id = str(res.get("clientIdentifier") or "")
            name = str(res.get("name") or "Plex Server")
            owned = 1 if res.get("owned") else 0
            owner_name = "You (Local)" if owned else str(res.get("sourceTitle") or "Shared Friend")
            srv_token = str(res.get("accessToken") or plex_token)
            conns = res.get("connections") or []

            candidates: list[tuple[str, bool, bool]] = []
            seen_uris: set[str] = set()
            if owned:
                # Always include direct localhost check for a local Mac Plex Media Server
                candidates.append(("http://127.0.0.1:32400", True, False))
                seen_uris.add("http://127.0.0.1:32400")

            for c in conns:
                uri = str(c.get("uri") or "").rstrip("/")
                if not uri or uri in seen_uris:
                    continue
                seen_uris.add(uri)
                is_local = bool(c.get("local"))
                is_relay = bool(c.get("relay"))
                # Skip unreachable RFC1918 local IPs advertised by remote friends' servers unless same LAN
                candidates.append((uri, is_local, is_relay))

            probes = await asyncio.gather(
                *[
                    _probe_server_connection(client, uri, srv_token, is_loc, is_rel)
                    for (uri, is_loc, is_rel) in candidates
                ]
            )
            valid = [p for p in probes if p is not None]
            if not valid:
                return {
                    "machine_id": machine_id,
                    "name": name,
                    "owned": owned,
                    "owner_name": owner_name,
                    "base_url": "",
                    "access_token": srv_token,
                    "is_local_conn": 0,
                    "is_relay": 0,
                    "latency_ms": 0,
                    "online": 0,
                    "enabled": existing_enabled.get(machine_id, 1),
                    "sections": [],
                }

            # Prefer non-relay over relay, local LAN when owned, then lowest latency
            best = sorted(
                valid,
                key=lambda p: (
                    0 if not p["is_relay"] else 1,
                    0 if (owned and p["is_local"]) else 1,
                    p["latency_ms"],
                ),
            )[0]
            return {
                "machine_id": machine_id,
                "name": name,
                "owned": owned,
                "owner_name": owner_name,
                "base_url": best["uri"],
                "access_token": srv_token,
                "is_local_conn": 1 if best["is_local"] else 0,
                "is_relay": 1 if best["is_relay"] else 0,
                "latency_ms": best["latency_ms"],
                "online": 1,
                "enabled": existing_enabled.get(machine_id, 1),
                "sections": best["sections"],
            }

        resolved = await asyncio.gather(*[resolve_resource(r) for r in server_resources])

    with db_session() as conn:
        for srv in resolved:
            conn.execute(
                """
                INSERT INTO servers (
                    machine_id, name, owned, owner_name, base_url, access_token,
                    is_local_conn, is_relay, latency_ms, online, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    name = excluded.name,
                    owned = excluded.owned,
                    owner_name = excluded.owner_name,
                    base_url = CASE WHEN excluded.online = 1 THEN excluded.base_url ELSE servers.base_url END,
                    access_token = excluded.access_token,
                    is_local_conn = excluded.is_local_conn,
                    is_relay = excluded.is_relay,
                    latency_ms = excluded.latency_ms,
                    online = excluded.online
                """,
                (
                    srv["machine_id"],
                    srv["name"],
                    srv["owned"],
                    srv["owner_name"],
                    srv["base_url"],
                    srv["access_token"],
                    srv["is_local_conn"],
                    srv["is_relay"],
                    srv["latency_ms"],
                    srv["online"],
                    srv["enabled"],
                ),
            )

    return resolved


async def fetch_watchlist_keys(client: httpx.AsyncClient, plex_token: str) -> set[str]:
    """Fetch all ratingKeys currently on the user's cloud Plex Watchlist."""
    keys: set[str] = set()
    offset = 0
    page_size = 150
    try:
        while True:
            resp = await client.get(
                f"{PLEX_DISCOVER_BASE}/library/sections/watchlist/all",
                headers=plex_headers(token=plex_token),
                params={
                    "includeCollections": "1",
                    "includeExternalMedia": "1",
                    "X-Plex-Container-Start": str(offset),
                    "X-Plex-Container-Size": str(page_size),
                },
                timeout=12.0,
            )
            if resp.status_code != 200:
                break
            mc = resp.json().get("MediaContainer", {})
            items = mc.get("Metadata") or []
            for it in items:
                rk = str(it.get("ratingKey") or "")
                guid = str(it.get("guid") or "")
                if rk:
                    keys.add(rk)
                if guid.startswith("plex://"):
                    keys.add(guid.rsplit("/", 1)[-1])
            total = int(mc.get("totalSize") or len(items))
            offset += len(items)
            if not items or offset >= total:
                break
    except Exception as exc:
        logger.warning("Could not fetch Plex watchlist: %s", exc)
    return keys


async def _fetch_section_items(
    client: httpx.AsyncClient,
    base_url: str,
    access_token: str,
    section_key: str,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    offset = 0
    page_size = 250
    while True:
        resp = await client.get(
            f"{base_url}/library/sections/{section_key}/all",
            headers=plex_headers(token=access_token),
            params={
                "includeGuids": "1",
                "X-Plex-Container-Start": str(offset),
                "X-Plex-Container-Size": str(page_size),
            },
            timeout=25.0,
        )
        resp.raise_for_status()
        mc = resp.json().get("MediaContainer", {})
        batch = mc.get("Metadata") or []
        all_items.extend(batch)
        total = int(mc.get("totalSize") or len(batch))
        offset += len(batch)
        if not batch or offset >= total:
            break
    return all_items


def _extract_tags(item: dict[str, Any], field: str, limit: int = 12) -> list[str]:
    entries = item.get(field) or []
    out: list[str] = []
    for entry in entries[:limit]:
        tag = str(entry.get("tag") or "").strip()
        if tag and tag not in out:
            out.append(tag)
    return out


async def sync_all_servers(on_complete_hook: Any | None = None) -> dict[str, Any]:
    """
    Full parallel sync across user's local Plex server(s) and all friends' shared Plex servers.
    """
    if SYNC_STATE.running:
        return SYNC_STATE.to_dict()

    plex_token = get_setting("plex_token")
    if not plex_token:
        raise ValueError("Not signed into Plex yet.")

    SYNC_STATE.running = True
    SYNC_STATE.phase = "discovering"
    SYNC_STATE.message = "Discovering your local & shared Plex servers..."
    SYNC_STATE.error = None
    SYNC_STATE.items_indexed = 0
    SYNC_STATE.completed_servers = 0
    SYNC_STATE.servers_detail = {}
    SYNC_STATE.started_at = int(time.time())
    SYNC_STATE.finished_at = None

    try:
        resolved_servers = await discover_and_probe_servers(plex_token)
        active_servers = [s for s in resolved_servers if s["online"] and s["enabled"]]
        SYNC_STATE.total_servers = len(active_servers)
        for s in resolved_servers:
            SYNC_STATE.servers_detail[s["machine_id"]] = {
                "machine_id": s["machine_id"],
                "name": s["name"],
                "owned": bool(s["owned"]),
                "owner_name": s["owner_name"],
                "online": bool(s["online"]),
                "enabled": bool(s["enabled"]),
                "status": "queued" if (s["online"] and s["enabled"]) else ("offline" if not s["online"] else "disabled"),
                "items": 0,
            }

        async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
            SYNC_STATE.phase = "watchlist"
            SYNC_STATE.message = "Syncing your universal Plex Watchlist..."
            watchlist_keys = await fetch_watchlist_keys(client, plex_token)

            SYNC_STATE.phase = "indexing"
            sem = asyncio.Semaphore(4)

            async def harvest_server(srv: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any]]]]:
                mid = srv["machine_id"]
                SYNC_STATE.servers_detail[mid]["status"] = "syncing"
                SYNC_STATE.message = f"Indexing {srv['name']}..."
                collected: list[tuple[str, str, dict[str, Any]]] = []
                async with sem:
                    sections = [
                        sec
                        for sec in (srv.get("sections") or [])
                        if sec.get("type") in ("movie", "show")
                    ]
                    for sec in sections:
                        sec_key = str(sec.get("key") or "")
                        sec_title = str(sec.get("title") or "")
                        sec_type = str(sec.get("type") or "")
                        if not sec_key:
                            continue
                        try:
                            items = await _fetch_section_items(
                                client, srv["base_url"], srv["access_token"], sec_key
                            )
                            for it in items:
                                collected.append((sec_key, sec_title, {**it, "_media_type": sec_type}))
                            SYNC_STATE.servers_detail[mid]["items"] = len(collected)
                        except Exception as sec_exc:
                            logger.warning(
                                "Failed syncing section %s on %s: %s", sec_title, srv["name"], sec_exc
                            )

                SYNC_STATE.completed_servers += 1
                SYNC_STATE.servers_detail[mid]["status"] = "done"
                return srv, collected

            harvest_results = await asyncio.gather(*[harvest_server(s) for s in active_servers])

        SYNC_STATE.phase = "merging"
        SYNC_STATE.message = "Deduplicating libraries & computing cross-server watch signals..."

        now_ts = int(time.time())
        abandoned_cutoff = now_ts - (21 * 86400)

        with db_session() as conn:
            # Map existing canonical keys -> media_id
            existing_map: dict[str, int] = {
                r["canonical_key"]: int(r["id"])
                for r in conn.execute("SELECT id, canonical_key FROM media_items").fetchall()
            }

            synced_machine_ids = [s["machine_id"] for s, _ in harvest_results]
            for mid in synced_machine_ids:
                conn.execute("DELETE FROM media_sources WHERE machine_id = ?", (mid,))

            for srv, raw_items in harvest_results:
                mid = srv["machine_id"]
                owned = int(srv["owned"])
                movie_cnt = 0
                show_cnt = 0

                for sec_key, sec_title, item in raw_items:
                    mtype = "movie" if item.get("_media_type") == "movie" else "show"
                    if mtype == "movie":
                        movie_cnt += 1
                    else:
                        show_cnt += 1

                    canonical_key, plex_guid, discover_rk, imdb_id, tmdb_id = extract_canonical_identity(
                        item, mtype
                    )
                    title = str(item.get("title") or "Untitled").strip()
                    orig_title = item.get("originalTitle")
                    year = int(item["year"]) if item.get("year") else None
                    tagline = str(item.get("tagline") or "")
                    summary = str(item.get("summary") or "")
                    content_rating = str(item.get("contentRating") or "")
                    duration_ms = int(item.get("duration") or 0)
                    duration_min = round(duration_ms / 60000) if duration_ms >= 60000 else None
                    critic_rating = float(item["rating"]) if item.get("rating") is not None else None
                    audience_rating = (
                        float(item["audienceRating"]) if item.get("audienceRating") is not None else None
                    )

                    genres = _extract_tags(item, "Genre", 8)
                    directors = _extract_tags(item, "Director", 5)
                    writers = _extract_tags(item, "Writer", 5)
                    cast = _extract_tags(item, "Role", 8)
                    countries = _extract_tags(item, "Country", 4)
                    studios: list[str] = []
                    if item.get("studio"):
                        studios.append(str(item["studio"]).strip())
                    collections = _extract_tags(item, "Collection", 4)

                    thumb = str(item.get("thumb") or "")
                    art = str(item.get("art") or "")

                    media_id = existing_map.get(canonical_key)
                    if media_id is None:
                        cur = conn.execute(
                            """
                            INSERT INTO media_items (
                                canonical_key, media_type, plex_guid, discover_rating_key, imdb_id, tmdb_id,
                                title, original_title, year, tagline, summary, content_rating, duration_min,
                                critic_rating, audience_rating, genres_json, directors_json, writers_json,
                                cast_json, countries_json, studios_json, collections_json,
                                poster_server_id, poster_path, art_path, is_external_only
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                            """,
                            (
                                canonical_key,
                                mtype,
                                plex_guid,
                                discover_rk,
                                imdb_id,
                                tmdb_id,
                                title,
                                orig_title,
                                year,
                                tagline,
                                summary,
                                content_rating,
                                duration_min,
                                critic_rating,
                                audience_rating,
                                json.dumps(genres),
                                json.dumps(directors),
                                json.dumps(writers),
                                json.dumps(cast),
                                json.dumps(countries),
                                json.dumps(studios),
                                json.dumps(collections),
                                mid if thumb else None,
                                thumb or None,
                                art or None,
                            ),
                        )
                        media_id = int(cur.lastrowid)
                        existing_map[canonical_key] = media_id
                    else:
                        # Enrich missing fields and prefer owned server for poster fetching speed
                        conn.execute(
                            """
                            UPDATE media_items SET
                                plex_guid = COALESCE(plex_guid, ?),
                                discover_rating_key = COALESCE(discover_rating_key, ?),
                                imdb_id = COALESCE(imdb_id, ?),
                                tmdb_id = COALESCE(tmdb_id, ?),
                                summary = CASE WHEN length(summary) < length(?) THEN ? ELSE summary END,
                                tagline = CASE WHEN tagline = '' THEN ? ELSE tagline END,
                                critic_rating = COALESCE(critic_rating, ?),
                                audience_rating = COALESCE(audience_rating, ?),
                                genres_json = CASE WHEN genres_json = '[]' THEN ? ELSE genres_json END,
                                directors_json = CASE WHEN directors_json = '[]' THEN ? ELSE directors_json END,
                                writers_json = CASE WHEN writers_json = '[]' THEN ? ELSE writers_json END,
                                cast_json = CASE WHEN cast_json = '[]' THEN ? ELSE cast_json END,
                                studios_json = CASE WHEN studios_json = '[]' THEN ? ELSE studios_json END,
                                poster_server_id = CASE WHEN (? = 1 AND ? != '') OR poster_server_id IS NULL THEN ? ELSE poster_server_id END,
                                poster_path = CASE WHEN (? = 1 AND ? != '') OR poster_path IS NULL THEN ? ELSE poster_path END,
                                is_external_only = 0
                            WHERE id = ?
                            """,
                            (
                                plex_guid,
                                discover_rk,
                                imdb_id,
                                tmdb_id,
                                summary,
                                summary,
                                tagline,
                                critic_rating,
                                audience_rating,
                                json.dumps(genres),
                                json.dumps(directors),
                                json.dumps(writers),
                                json.dumps(cast),
                                json.dumps(studios),
                                owned,
                                thumb,
                                mid if thumb else None,
                                owned,
                                thumb,
                                thumb or None,
                                media_id,
                            ),
                        )

                    res_label, codec, hdr = parse_resolution(item.get("Media"))
                    rating_key = str(item.get("ratingKey") or "")
                    view_count = int(item.get("viewCount") or 0)
                    view_offset_ms = int(item.get("viewOffset") or 0)
                    viewed_leaves = int(item.get("viewedLeafCount") or 0)
                    total_leaves = int(item.get("leafCount") or 0)
                    user_rating = (
                        float(item["userRating"]) if item.get("userRating") is not None else None
                    )
                    last_viewed = int(item["lastViewedAt"]) if item.get("lastViewedAt") else None
                    added_at = int(item["addedAt"]) if item.get("addedAt") else None

                    if rating_key:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO media_sources (
                                media_id, machine_id, rating_key, section_id, section_title,
                                resolution, video_codec, hdr, view_count, view_offset_ms, duration_ms,
                                viewed_leaf_count, leaf_count, user_rating, last_viewed_at, added_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                media_id,
                                mid,
                                rating_key,
                                sec_key,
                                sec_title,
                                res_label,
                                codec,
                                hdr,
                                view_count,
                                view_offset_ms,
                                duration_ms,
                                viewed_leaves,
                                total_leaves,
                                user_rating,
                                last_viewed,
                                added_at,
                            ),
                        )
                    SYNC_STATE.items_indexed += 1

                conn.execute(
                    """
                    UPDATE servers SET movie_count = ?, show_count = ?, last_synced_at = ?
                    WHERE machine_id = ?
                    """,
                    (movie_cnt, show_cnt, now_ts, mid),
                )

            # Recompute cross-server aggregated watch state, abandonment, and watchlist status
            all_media = conn.execute(
                """
                SELECT id, media_type, discover_rating_key,
                       netflix_watched_count, netflix_abandoned, netflix_last_viewed_at
                FROM media_items
                """
            ).fetchall()

            src_grouped: dict[int, list[sqlite3.Row]] = {}
            for srow in conn.execute("SELECT * FROM media_sources").fetchall():
                src_grouped.setdefault(int(srow["media_id"]), []).append(srow)

            for mrow in all_media:
                mid_int = int(mrow["id"])
                mtype = mrow["media_type"]
                drk = mrow["discover_rating_key"]
                nf_cnt = int(mrow["netflix_watched_count"] or 0)
                nf_aband = int(mrow["netflix_abandoned"] or 0)
                nf_lv = int(mrow["netflix_last_viewed_at"]) if mrow["netflix_last_viewed_at"] else None
                srcs = src_grouped.get(mid_int, [])

                if not srcs:
                    on_wl = 1 if (drk and drk in watchlist_keys) else 0
                    conn.execute(
                        """
                        UPDATE media_items
                        SET on_watchlist = ?, is_external_only = 1,
                            is_watched = CASE WHEN ? > 0 THEN 1 ELSE is_watched END
                        WHERE id = ?
                        """,
                        (on_wl, nf_cnt, mid_int),
                    )
                    continue

                max_vc = max(int(s["view_count"] or 0) for s in srcs)
                ratings = [float(s["user_rating"]) for s in srcs if s["user_rating"] is not None]
                max_ur = max(ratings) if ratings else None
                max_leaves = max(int(s["leaf_count"] or 0) for s in srcs)
                max_viewed_leaves = max(int(s["viewed_leaf_count"] or 0) for s in srcs)
                lvs = [int(s["last_viewed_at"]) for s in srcs if s["last_viewed_at"]]
                if nf_lv:
                    lvs.append(nf_lv)
                last_viewed = max(lvs) if lvs else None
                adds = [int(s["added_at"]) for s in srcs if s["added_at"]]
                latest_added = max(adds) if adds else None

                max_prog = 0.0
                for s in srcs:
                    dur = int(s["duration_ms"] or 0)
                    off = int(s["view_offset_ms"] or 0)
                    if dur > 0 and off > 0:
                        max_prog = max(max_prog, min(1.0, off / dur))

                is_watched = 1 if nf_cnt > 0 else 0
                is_abandoned = 0
                if mtype == "movie":
                    if max_vc >= 1 or nf_cnt >= 1:
                        is_watched = 1
                    elif 0.08 <= max_prog <= 0.72 and last_viewed and last_viewed < abandoned_cutoff:
                        is_watched = 1
                        is_abandoned = 1
                else:
                    eff_viewed = max(max_viewed_leaves, nf_cnt)
                    if max_leaves > 0:
                        ep_ratio = eff_viewed / max_leaves
                    else:
                        ep_ratio = 0.0
                    if max_vc >= 1 or eff_viewed >= 3 or ep_ratio >= 0.35:
                        is_watched = 1
                    elif (
                        eff_viewed in (1, 2)
                        and ep_ratio <= 0.25
                        and last_viewed
                        and last_viewed < abandoned_cutoff
                    ) or (nf_aband == 1 and max_viewed_leaves < 3):
                        is_watched = 1
                        is_abandoned = 1
                    max_prog = max(max_prog, min(1.0, ep_ratio))

                on_wl = 1 if (drk and drk in watchlist_keys) else 0
                conn.execute(
                    """
                    UPDATE media_items SET
                        is_watched = ?,
                        max_view_count = ?,
                        max_user_rating = ?,
                        leaf_count = ?,
                        viewed_leaf_count = ?,
                        max_progress_ratio = ?,
                        is_abandoned = ?,
                        last_viewed_at = ?,
                        latest_added_at = ?,
                        on_watchlist = ?,
                        is_external_only = 0
                    WHERE id = ?
                    """,
                    (
                        is_watched,
                        max_vc,
                        max_ur,
                        max_leaves,
                        max_viewed_leaves,
                        round(max_prog, 3),
                        is_abandoned,
                        last_viewed,
                        latest_added,
                        on_wl,
                        mid_int,
                    ),
                )

        # Also sync Netflix catalog if enabled
        SYNC_STATE.phase = "netflix"
        SYNC_STATE.message = "Indexing regional Netflix catalog..."
        from .netflix_service import sync_netflix_catalog
        nf_stats = await sync_netflix_catalog(watchlist_keys=watchlist_keys)
        nf_total = int(nf_stats.get("total") or 0)
        SYNC_STATE.items_indexed += nf_total

        set_setting("last_sync_at", str(now_ts))
        SYNC_STATE.phase = "done"
        nf_suffix = f" + {nf_total:,} Netflix titles" if nf_total else ""
        SYNC_STATE.message = f"Synced {SYNC_STATE.items_indexed:,} items ({len(active_servers)} Plex server(s){nf_suffix})."
        SYNC_STATE.finished_at = int(time.time())
        if on_complete_hook:
            on_complete_hook()
    except Exception as exc:
        logger.exception("Sync failed")
        SYNC_STATE.phase = "error"
        SYNC_STATE.error = str(exc)
        SYNC_STATE.message = f"Sync error: {exc}"
    finally:
        SYNC_STATE.running = False

    return SYNC_STATE.to_dict()


async def resolve_discover_rating_key(
    client: httpx.AsyncClient,
    plex_token: str,
    title: str,
    year: int | None,
    media_type: str,
) -> dict[str, Any] | None:
    """Resolve an item in Plex's global Discover catalog to obtain its ratingKey & rich metadata."""
    search_type = "movies" if media_type == "movie" else "tv"
    resp = await client.get(
        f"{PLEX_DISCOVER_BASE}/library/search",
        headers=plex_headers(token=plex_token),
        params={
            "query": title,
            "limit": "8",
            "searchTypes": search_type,
            "searchProviders": "discover",
            "includeMetadata": "1",
        },
        timeout=12.0,
    )
    if resp.status_code != 200:
        return None
    results = resp.json().get("MediaContainer", {}).get("SearchResults") or []
    candidates: list[dict[str, Any]] = []
    for group in results:
        for sr in group.get("SearchResult") or []:
            md = sr.get("Metadata")
            if md and md.get("type") == media_type:
                candidates.append(md)

    if not candidates:
        return None

    norm_target = normalize_title_key(title)
    best = None
    best_score = -1
    for md in candidates:
        score = 0
        if normalize_title_key(md.get("title", "")) == norm_target:
            score += 5
        if year and md.get("year") and abs(int(md["year"]) - int(year)) <= 1:
            score += 4
        if score > best_score:
            best_score = score
            best = md
    return best


async def toggle_plex_watchlist(media_id: int, target_on: bool) -> dict[str, Any]:
    plex_token = get_setting("plex_token")
    if not plex_token:
        raise ValueError("Sign into Plex to sync with your Plex Watchlist.")

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, title, year, media_type, discover_rating_key FROM media_items WHERE id = ?",
            (media_id,),
        ).fetchone()
        if not row:
            raise ValueError("Media item not found.")

    discover_rk = row["discover_rating_key"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        if not discover_rk:
            resolved = await resolve_discover_rating_key(
                client, plex_token, row["title"], row["year"], row["media_type"]
            )
            if resolved and resolved.get("ratingKey"):
                discover_rk = str(resolved["ratingKey"])
                with db_session() as conn:
                    conn.execute(
                        "UPDATE media_items SET discover_rating_key = ? WHERE id = ?",
                        (discover_rk, media_id),
                    )
            else:
                raise ValueError(
                    f"Could not match '{row['title']}' in Plex's cloud Watchlist catalog."
                )

        action = "addToWatchlist" if target_on else "removeFromWatchlist"
        resp = await client.put(
            f"{PLEX_DISCOVER_BASE}/actions/{action}",
            headers=plex_headers(token=plex_token),
            params={"ratingKey": discover_rk},
        )
        # 200 or 204 succeeds; 400 if already in target state
        if resp.status_code not in (200, 201, 204, 400):
            resp.raise_for_status()

    with db_session() as conn:
        conn.execute(
            "UPDATE media_items SET on_watchlist = ? WHERE id = ?",
            (1 if target_on else 0, media_id),
        )

    return {"media_id": media_id, "on_watchlist": target_on, "discover_rating_key": discover_rk}


async def upsert_discover_item(md: dict[str, Any]) -> int:
    """Insert or return media_id for a movie/show from Plex's global Discover catalog."""
    rk = str(md.get("ratingKey") or "")
    mtype = "movie" if md.get("type") == "movie" else "show"
    plex_guid = str(md.get("guid") or (f"plex://{mtype}/{rk}" if rk else ""))
    if not rk and plex_guid.startswith("plex://"):
        rk = plex_guid.rsplit("/", 1)[-1]
    canonical = f"plex:{mtype}:{rk}" if rk else f"title:{mtype}:{normalize_title_key(md.get('title', ''))}:{md.get('year') or 0}"

    with db_session() as conn:
        existing = conn.execute(
            "SELECT id FROM media_items WHERE canonical_key = ? OR (discover_rating_key IS NOT NULL AND discover_rating_key = ?)",
            (canonical, rk),
        ).fetchone()
        if existing:
            return int(existing["id"])

        genres = _extract_tags(md, "Genre", 8)
        directors = _extract_tags(md, "Director", 5)
        writers = _extract_tags(md, "Writer", 5)
        cast = _extract_tags(md, "Role", 8)
        duration_ms = int(md.get("duration") or 0)
        duration_min = round(duration_ms / 60000) if duration_ms >= 60000 else None
        thumb = str(md.get("thumb") or "")
        ext_poster = thumb if thumb.startswith("http") else None

        cur = conn.execute(
            """
            INSERT INTO media_items (
                canonical_key, media_type, plex_guid, discover_rating_key,
                title, year, tagline, summary, content_rating, duration_min,
                critic_rating, audience_rating, genres_json, directors_json,
                writers_json, cast_json, poster_url_external, is_external_only
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                canonical,
                mtype,
                plex_guid or None,
                rk or None,
                str(md.get("title") or "Untitled"),
                int(md["year"]) if md.get("year") else None,
                str(md.get("tagline") or ""),
                str(md.get("summary") or ""),
                str(md.get("contentRating") or ""),
                duration_min,
                float(md["rating"]) if md.get("rating") is not None else None,
                float(md["audienceRating"]) if md.get("audienceRating") is not None else None,
                json.dumps(genres),
                json.dumps(directors),
                json.dumps(writers),
                json.dumps(cast),
                ext_poster,
            ),
        )
        return int(cur.lastrowid)


async def fetch_outside_discover_candidates(
    seed_rating_keys: list[str],
    media_type_filter: str = "all",
    limit: int = 16,
) -> list[int]:
    """
    Fetch non-commercial related/similar discoveries from Plex's global metadata catalog
    based on the user's highest-affinity watched titles (works even without an LLM key!).
    """
    plex_token = get_setting("plex_token")
    if not plex_token or not seed_rating_keys:
        return []

    discovered_ids: list[int] = []
    seen_rks: set[str] = set()

    async with httpx.AsyncClient(timeout=12.0) as client:
        async def fetch_for_seed(rk: str) -> list[dict[str, Any]]:
            try:
                resp = await client.get(
                    f"{PLEX_METADATA_BASE}/library/metadata/{rk}/similar",
                    headers=plex_headers(token=plex_token),
                    params={"limit": "10", "includeUserState": "1"},
                )
                if resp.status_code != 200:
                    return []
                return resp.json().get("MediaContainer", {}).get("Metadata") or []
            except Exception:
                return []

        batches = await asyncio.gather(*[fetch_for_seed(rk) for rk in seed_rating_keys[:6]])

        for batch in batches:
            for md in batch:
                rk = str(md.get("ratingKey") or "")
                mtype = str(md.get("type") or "")
                if mtype not in ("movie", "show"):
                    continue
                if media_type_filter in ("movie", "show") and mtype != media_type_filter:
                    continue
                if not rk or rk in seen_rks:
                    continue
                # Skip if user already watched in cloud userState
                if int(md.get("viewCount") or 0) > 0:
                    continue
                seen_rks.add(rk)
                # Fetch full metadata from metadata.provider.plex.tv so directors/cast/genres are populated
                try:
                    d_resp = await client.get(
                        f"{PLEX_METADATA_BASE}/library/metadata/{rk}",
                        headers=plex_headers(token=plex_token),
                    )
                    if d_resp.status_code == 200:
                        full_list = d_resp.json().get("MediaContainer", {}).get("Metadata") or []
                        if full_list:
                            md = full_list[0]
                except Exception:
                    pass

                mid = await upsert_discover_item(md)
                discovered_ids.append(mid)
                if len(discovered_ids) >= limit:
                    return discovered_ids

    return discovered_ids


async def fetch_poster_bytes(media_id: int) -> tuple[bytes, str] | None:
    ensure_data_dirs()
    cache_file = POSTER_CACHE_DIR / f"{media_id}.jpg"
    if cache_file.exists() and cache_file.stat().st_size > 200:
        return cache_file.read_bytes(), "image/jpeg"

    with db_session() as conn:
        row = conn.execute(
            "SELECT poster_server_id, poster_path, poster_url_external FROM media_items WHERE id = ?",
            (media_id,),
        ).fetchone()
        if not row:
            return None

        ext_url = row["poster_url_external"]
        srv_id = row["poster_server_id"]
        poster_path = row["poster_path"]

        srv_row = None
        if srv_id:
            srv_row = conn.execute(
                "SELECT base_url, access_token FROM servers WHERE machine_id = ?",
                (srv_id,),
            ).fetchone()

    plex_token = get_setting("plex_token")
    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=10.0) as client:
        if srv_row and srv_row["base_url"] and poster_path:
            base_url = srv_row["base_url"].rstrip("/")
            token = srv_row["access_token"]
            transcode_url = (
                f"{base_url}/photo/:/transcode"
                f"?width=360&height=540&minSize=1&upscale=1&url={quote(poster_path, safe='')}"
            )
            try:
                resp = await client.get(transcode_url, headers=plex_headers(token=token))
                if resp.status_code == 200 and len(resp.content) > 200:
                    cache_file.write_bytes(resp.content)
                    return resp.content, resp.headers.get("content-type", "image/jpeg")
            except Exception:
                pass

        if ext_url:
            try:
                headers = plex_headers(token=plex_token) if "plex.tv" in ext_url else {}
                resp = await client.get(ext_url, headers=headers)
                if resp.status_code == 200 and len(resp.content) > 200:
                    cache_file.write_bytes(resp.content)
                    return resp.content, resp.headers.get("content-type", "image/jpeg")
            except Exception:
                pass

    return None


def build_plex_deep_link(machine_id: str, rating_key: str) -> str:
    encoded_key = quote(f"/library/metadata/{rating_key}", safe="")
    return f"https://app.plex.tv/desktop#!/server/{machine_id}/details?key={encoded_key}"
