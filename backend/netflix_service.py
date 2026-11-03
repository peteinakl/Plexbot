from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from .db import db_session, get_setting
from .plex_client import (
    PLEX_DISCOVER_BASE,
    PLEX_METADATA_BASE,
    _extract_tags,
    normalize_title_key,
    plex_headers,
    resolve_discover_rating_key,
)

logger = logging.getLogger("plexbot.netflix")

NETFLIX_MACHINE_ID = "provider:netflix"

TMDB_GENRE_MAP: dict[int, str] = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
    10759: "Action & Adventure",
    10762: "Kids",
    10765: "Science Fiction",
    10768: "War & Politics",
}

EPISODE_SPLIT_RE = re.compile(
    r"^(?P<show>.+?):\s*(?:"
    r"Season\s*\d+|Series\s*\d+|Part\s*\d+|Volume\s*\d+|Vol\.\s*\d+|"
    r"Book\s*\d+|Chapter\s*\d+|Limited\s+Series|Miniseries|Collection.*|"
    r"Episode\s*\d+|Ep\.\s*\d+|S\d+\s*E\d+"
    r")\b.*$",
    re.IGNORECASE,
)


def ensure_netflix_server_row() -> dict[str, Any]:
    with db_session() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO servers (
                machine_id, name, owned, owner_name, base_url, access_token,
                is_local_conn, is_relay, latency_ms, online, enabled, source_type
            ) VALUES (
                ?, 'Netflix', 0, 'Streaming Subscription',
                'https://www.netflix.com', '', 0, 0, 20, 1, 1, 'streaming'
            )
            """,
            (NETFLIX_MACHINE_ID,),
        )
        row = conn.execute(
            "SELECT * FROM servers WHERE machine_id = ?", (NETFLIX_MACHINE_ID,)
        ).fetchone()
        return dict(row)


def _upsert_streaming_catalog_item(
    conn: Any,
    existing_by_ckey: dict[str, int],
    existing_by_drk: dict[str, int],
    existing_by_title_yr: dict[tuple[str, str, int], int],
    *,
    canonical_key: str,
    media_type: str,
    plex_guid: str | None,
    discover_rk: str | None,
    tmdb_id: str | None,
    title: str,
    year: int | None,
    tagline: str,
    summary: str,
    content_rating: str,
    duration_min: int | None,
    critic_rating: float | None,
    audience_rating: float | None,
    genres: list[str],
    directors: list[str],
    writers: list[str],
    cast: list[str],
    countries: list[str],
    studios: list[str],
    poster_url_external: str | None,
    cloud_watched: bool,
    watchlist_keys: set[str],
) -> int:
    norm_t = normalize_title_key(title)
    yr_key = int(year or 0)

    media_id = None
    if discover_rk and discover_rk in existing_by_drk:
        media_id = existing_by_drk[discover_rk]
    elif canonical_key in existing_by_ckey:
        media_id = existing_by_ckey[canonical_key]
    elif (media_type, norm_t, yr_key) in existing_by_title_yr:
        media_id = existing_by_title_yr[(media_type, norm_t, yr_key)]

    on_wl = 1 if (discover_rk and discover_rk in watchlist_keys) else 0

    if media_id is None:
        cur = conn.execute(
            """
            INSERT INTO media_items (
                canonical_key, media_type, plex_guid, discover_rating_key, tmdb_id,
                title, year, tagline, summary, content_rating, duration_min,
                critic_rating, audience_rating, genres_json, directors_json, writers_json,
                cast_json, countries_json, studios_json, poster_url_external,
                is_watched, max_view_count, on_watchlist, is_external_only
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                canonical_key,
                media_type,
                plex_guid,
                discover_rk,
                tmdb_id,
                title,
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
                poster_url_external,
                1 if cloud_watched else 0,
                1 if cloud_watched else 0,
                on_wl,
            ),
        )
        media_id = int(cur.lastrowid)
        existing_by_ckey[canonical_key] = media_id
        if discover_rk:
            existing_by_drk[discover_rk] = media_id
        existing_by_title_yr[(media_type, norm_t, yr_key)] = media_id
    else:
        conn.execute(
            """
            UPDATE media_items SET
                plex_guid = COALESCE(plex_guid, ?),
                discover_rating_key = COALESCE(discover_rating_key, ?),
                tmdb_id = COALESCE(tmdb_id, ?),
                summary = CASE WHEN (summary IS NULL OR length(summary) < length(?)) THEN ? ELSE summary END,
                tagline = CASE WHEN (tagline IS NULL OR tagline = '') THEN ? ELSE tagline END,
                critic_rating = COALESCE(critic_rating, ?),
                audience_rating = COALESCE(audience_rating, ?),
                genres_json = CASE WHEN genres_json = '[]' AND ? != '[]' THEN ? ELSE genres_json END,
                directors_json = CASE WHEN directors_json = '[]' AND ? != '[]' THEN ? ELSE directors_json END,
                writers_json = CASE WHEN writers_json = '[]' AND ? != '[]' THEN ? ELSE writers_json END,
                cast_json = CASE WHEN cast_json = '[]' AND ? != '[]' THEN ? ELSE cast_json END,
                poster_url_external = COALESCE(poster_url_external, ?),
                is_watched = CASE WHEN ? = 1 THEN 1 ELSE is_watched END,
                is_external_only = 0
            WHERE id = ?
            """,
            (
                plex_guid,
                discover_rk,
                tmdb_id,
                summary,
                summary,
                tagline,
                critic_rating,
                audience_rating,
                json.dumps(genres),
                json.dumps(genres),
                json.dumps(directors),
                json.dumps(directors),
                json.dumps(writers),
                json.dumps(writers),
                json.dumps(cast),
                json.dumps(cast),
                poster_url_external,
                1 if cloud_watched else 0,
                media_id,
            ),
        )

    return media_id


async def _harvest_plex_discover_netflix(
    client: httpx.AsyncClient,
    plex_token: str,
) -> list[dict[str, Any]]:
    """
    Zero-API-key regional Netflix catalog harvest via Plex's Discover platform hubs + batch Metadata API.
    """
    headers = plex_headers(token=plex_token)
    hub_keys: list[str] = [
        "/library/platforms/netflix/trend",
        "/library/platforms/netflix/exclusives",
        "/library/platforms/netflix/recommended",
        "/library/platforms/netflix/recently-released",
        "/library/platforms/netflix/platform-popular",
        "/library/platforms/netflix/watchlist",
    ]

    try:
        plat_resp = await client.get(
            f"{PLEX_DISCOVER_BASE}/library/platforms/netflix", headers=headers, timeout=12.0
        )
        if plat_resp.status_code == 200:
            for h in plat_resp.json().get("MediaContainer", {}).get("Hub") or []:
                hk = str(h.get("key") or "")
                htype = str(h.get("type") or "")
                if hk and htype == "mixed" and hk not in hub_keys:
                    hub_keys.append(hk)

        genres_resp = await client.get(
            f"{PLEX_DISCOVER_BASE}/library/platforms/netflix/popular-genres",
            headers=headers,
            timeout=10.0,
        )
        if genres_resp.status_code == 200:
            for d in genres_resp.json().get("MediaContainer", {}).get("Directory") or []:
                dk = str(d.get("key") or "")
                if dk and dk not in hub_keys:
                    hub_keys.append(dk)
    except Exception as exc:
        logger.warning("Error listing Netflix platform hubs: %s", exc)

    # Also run several independent 'random' ("Surprise Me") pulls to capture deeper catalog gems
    random_calls = [f"/library/platforms/netflix/random?_r={i}" for i in range(10)]
    all_paths = hub_keys + random_calls

    sem = asyncio.Semaphore(6)

    async def fetch_hub(path: str) -> list[dict[str, Any]]:
        async with sem:
            try:
                sep = "&" if "?" in path else "?"
                url = f"{PLEX_DISCOVER_BASE}{path}{sep}X-Plex-Container-Start=0&X-Plex-Container-Size=100"
                r = await client.get(url, headers=headers, timeout=12.0)
                if r.status_code == 200:
                    return r.json().get("MediaContainer", {}).get("Metadata") or []
            except Exception:
                pass
            return []

    hub_batches = await asyncio.gather(*[fetch_hub(p) for p in all_paths])
    stubs_by_rk: dict[str, dict[str, Any]] = {}
    for batch in hub_batches:
        for md in batch:
            rk = str(md.get("ratingKey") or "")
            mtype = str(md.get("type") or "")
            if rk and mtype in ("movie", "show"):
                stubs_by_rk[rk] = md

    all_rks = list(stubs_by_rk.keys())
    if not all_rks:
        return []

    # Batch-enrich in chunks of 35 via metadata.provider.plex.tv for full Directors, Writers, Cast, Genres!
    enriched: list[dict[str, Any]] = []
    chunks = [all_rks[i : i + 35] for i in range(0, len(all_rks), 35)]

    async def fetch_metadata_chunk(rk_chunk: list[str]) -> list[dict[str, Any]]:
        async with sem:
            try:
                joined = ",".join(rk_chunk)
                r = await client.get(
                    f"{PLEX_METADATA_BASE}/library/metadata/{joined}",
                    headers=headers,
                    params={"includeUserState": "1"},
                    timeout=15.0,
                )
                if r.status_code == 200:
                    return r.json().get("MediaContainer", {}).get("Metadata") or []
            except Exception as exc:
                logger.warning("Batch metadata chunk warning: %s", exc)
            return [stubs_by_rk[k] for k in rk_chunk if k in stubs_by_rk]

    meta_batches = await asyncio.gather(*[fetch_metadata_chunk(c) for c in chunks])
    for mb in meta_batches:
        enriched.extend(mb)

    return enriched


async def _harvest_tmdb_netflix(
    client: httpx.AsyncClient,
    tmdb_key: str,
    region: str,
) -> list[dict[str, Any]]:
    """
    Optional deep Netflix regional catalog expansion via TMDB API (provider 8 = Netflix).
    Supports both v3 API keys and v4 Bearer Read Tokens.
    """
    clean_key = tmdb_key.strip()
    if not clean_key:
        return []

    headers = {"Accept": "application/json"}
    base_params: dict[str, str] = {
        "with_watch_providers": "8",
        "watch_region": region.upper() or "NZ",
        "include_adult": "false",
    }
    if clean_key.startswith("eyJ") or len(clean_key) > 45:
        headers["Authorization"] = f"Bearer {clean_key}"
    else:
        base_params["api_key"] = clean_key

    items: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(5)

    async def fetch_page(kind: str, sort_by: str, page: int, min_votes: int) -> list[dict[str, Any]]:
        async with sem:
            try:
                params = {
                    **base_params,
                    "sort_by": sort_by,
                    "page": str(page),
                    "vote_count.gte": str(min_votes),
                }
                r = await client.get(
                    f"https://api.themoviedb.org/3/discover/{kind}",
                    headers=headers,
                    params=params,
                    timeout=12.0,
                )
                if r.status_code == 200:
                    return [
                        {**it, "_tmdb_kind": kind}
                        for it in (r.json().get("results") or [])
                    ]
            except Exception:
                pass
            return []

    tasks = []
    for kind in ("movie", "tv"):
        for page in range(1, 6):
            tasks.append(fetch_page(kind, "popularity.desc", page, 40))
            tasks.append(fetch_page(kind, "vote_average.desc", page, 180))

    pages = await asyncio.gather(*tasks)
    seen_tmdb: set[tuple[str, int]] = set()
    for batch in pages:
        for it in batch:
            tid = int(it.get("id") or 0)
            kind = it["_tmdb_kind"]
            if tid and (kind, tid) not in seen_tmdb:
                seen_tmdb.add((kind, tid))
                items.append(it)
    return items


async def sync_netflix_catalog(watchlist_keys: set[str] | None = None) -> dict[str, Any]:
    """
    Index the regional Netflix catalog into media_items & media_sources ('provider:netflix').
    """
    srv = ensure_netflix_server_row()
    if not srv.get("enabled"):
        with db_session() as conn:
            conn.execute("DELETE FROM media_sources WHERE machine_id = ?", (NETFLIX_MACHINE_ID,))
            conn.execute(
                "UPDATE servers SET movie_count = 0, show_count = 0 WHERE machine_id = ?",
                (NETFLIX_MACHINE_ID,),
            )
        return {"synced": 0, "enabled": False}

    plex_token = get_setting("plex_token")
    tmdb_key = get_setting("tmdb_api_key")
    region = get_setting("watch_region", "NZ") or "NZ"
    wl_keys = watchlist_keys or set()

    async with httpx.AsyncClient(timeout=18.0, follow_redirects=True) as client:
        plex_items = (
            await _harvest_plex_discover_netflix(client, plex_token) if plex_token else []
        )
        tmdb_items = (
            await _harvest_tmdb_netflix(client, tmdb_key, region) if tmdb_key else []
        )

    now_ts = int(time.time())
    movie_cnt = 0
    show_cnt = 0
    seen_source_rks: set[str] = set()

    with db_session() as conn:
        existing_by_ckey: dict[str, int] = {}
        existing_by_drk: dict[str, int] = {}
        existing_by_title_yr: dict[tuple[str, str, int], int] = {}

        for r in conn.execute(
            "SELECT id, canonical_key, media_type, discover_rating_key, title, year FROM media_items"
        ).fetchall():
            mid = int(r["id"])
            existing_by_ckey[r["canonical_key"]] = mid
            if r["discover_rating_key"]:
                existing_by_drk[str(r["discover_rating_key"])] = mid
            existing_by_title_yr[
                (r["media_type"], normalize_title_key(r["title"]), int(r["year"] or 0))
            ] = mid

        # Preserve any previously resolved direct Netflix watch URLs
        cached_urls: dict[str, str] = {
            r["rating_key"]: r["external_url"]
            for r in conn.execute(
                "SELECT rating_key, external_url FROM media_sources WHERE machine_id = ? AND external_url != ''",
                (NETFLIX_MACHINE_ID,),
            ).fetchall()
        }

        conn.execute("DELETE FROM media_sources WHERE machine_id = ?", (NETFLIX_MACHINE_ID,))

        # 1. Upsert Plex Discover Netflix items (rich metadata with Directors/Writers/Cast!)
        for md in plex_items:
            mtype = "movie" if md.get("type") == "movie" else "show"
            rk = str(md.get("ratingKey") or "")
            if not rk:
                continue
            source_rk = f"nf:{rk}"
            if source_rk in seen_source_rks:
                continue
            seen_source_rks.add(source_rk)

            if mtype == "movie":
                movie_cnt += 1
            else:
                show_cnt += 1

            plex_guid = str(md.get("guid") or f"plex://{mtype}/{rk}")
            ckey = f"plex:{mtype}:{rk}"
            title = str(md.get("title") or "Untitled").strip()
            year = int(md["year"]) if md.get("year") else None
            duration_ms = int(md.get("duration") or 0)
            duration_min = round(duration_ms / 60000) if duration_ms >= 60000 else None
            thumb = str(md.get("thumb") or "")
            ext_poster = thumb if thumb.startswith("http") else None

            user_state = md.get("UserState") or md.get("userState") or {}
            cloud_watched = int(md.get("viewCount") or user_state.get("viewCount") or 0) > 0

            media_id = _upsert_streaming_catalog_item(
                conn,
                existing_by_ckey,
                existing_by_drk,
                existing_by_title_yr,
                canonical_key=ckey,
                media_type=mtype,
                plex_guid=plex_guid,
                discover_rk=rk,
                tmdb_id=None,
                title=title,
                year=year,
                tagline=str(md.get("tagline") or ""),
                summary=str(md.get("summary") or ""),
                content_rating=str(md.get("contentRating") or ""),
                duration_min=duration_min,
                critic_rating=float(md["rating"]) if md.get("rating") is not None else None,
                audience_rating=float(md["audienceRating"]) if md.get("audienceRating") is not None else None,
                genres=_extract_tags(md, "Genre", 8),
                directors=_extract_tags(md, "Director", 5),
                writers=_extract_tags(md, "Writer", 5),
                cast=_extract_tags(md, "Role", 8),
                countries=_extract_tags(md, "Country", 4),
                studios=[str(md["studio"]).strip()] if md.get("studio") else [],
                poster_url_external=ext_poster,
                cloud_watched=cloud_watched,
                watchlist_keys=wl_keys,
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO media_sources (
                    media_id, machine_id, rating_key, section_id, section_title,
                    resolution, added_at, external_url
                ) VALUES (?, ?, ?, 'netflix', ?, 'HD', ?, ?)
                """,
                (
                    media_id,
                    NETFLIX_MACHINE_ID,
                    source_rk,
                    f"Netflix ({region.upper()})",
                    now_ts,
                    cached_urls.get(source_rk, ""),
                ),
            )

        # 2. Upsert optional TMDB Netflix items
        for it in tmdb_items:
            kind = it["_tmdb_kind"]
            mtype = "movie" if kind == "movie" else "show"
            tid = str(it["id"])
            source_rk = f"nf_tmdb:{mtype}:{tid}"
            if source_rk in seen_source_rks:
                continue

            title = str(it.get("title") or it.get("name") or "Untitled").strip()
            raw_date = str(it.get("release_date") or it.get("first_air_date") or "")
            year = int(raw_date[:4]) if len(raw_date) >= 4 and raw_date[:4].isdigit() else None
            norm_t = normalize_title_key(title)

            # Skip if already added via Plex Discover in this run
            existing_mid = existing_by_title_yr.get((mtype, norm_t, int(year or 0)))
            if existing_mid is not None:
                already_src = conn.execute(
                    "SELECT 1 FROM media_sources WHERE media_id = ? AND machine_id = ?",
                    (existing_mid, NETFLIX_MACHINE_ID),
                ).fetchone()
                if already_src:
                    continue

            seen_source_rks.add(source_rk)
            if mtype == "movie":
                movie_cnt += 1
            else:
                show_cnt += 1

            genres = [
                TMDB_GENRE_MAP[gid]
                for gid in (it.get("genre_ids") or [])
                if gid in TMDB_GENRE_MAP
            ]
            poster_path = it.get("poster_path")
            ext_poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            vote = float(it["vote_average"]) if it.get("vote_average") else None

            media_id = _upsert_streaming_catalog_item(
                conn,
                existing_by_ckey,
                existing_by_drk,
                existing_by_title_yr,
                canonical_key=f"tmdb:{mtype}:{tid}",
                media_type=mtype,
                plex_guid=None,
                discover_rk=None,
                tmdb_id=tid,
                title=title,
                year=year,
                tagline="",
                summary=str(it.get("overview") or ""),
                content_rating="",
                duration_min=None,
                critic_rating=None,
                audience_rating=vote,
                genres=genres,
                directors=[],
                writers=[],
                cast=[],
                countries=[],
                studios=[],
                poster_url_external=ext_poster,
                cloud_watched=False,
                watchlist_keys=wl_keys,
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO media_sources (
                    media_id, machine_id, rating_key, section_id, section_title,
                    resolution, added_at, external_url
                ) VALUES (?, ?, ?, 'netflix', ?, 'HD', ?, ?)
                """,
                (
                    media_id,
                    NETFLIX_MACHINE_ID,
                    source_rk,
                    f"Netflix ({region.upper()})",
                    now_ts,
                    cached_urls.get(source_rk, ""),
                ),
            )

        conn.execute(
            """
            UPDATE servers
            SET movie_count = ?, show_count = ?, online = 1, last_synced_at = ?
            WHERE machine_id = ?
            """,
            (movie_cnt, show_cnt, now_ts, NETFLIX_MACHINE_ID),
        )

    return {
        "enabled": True,
        "region": region.upper(),
        "movies": movie_cnt,
        "shows": show_cnt,
        "total": movie_cnt + show_cnt,
    }


async def resolve_netflix_watch_url(media_id: int) -> str:
    """
    Resolve and cache the exact Netflix title URL (e.g. https://www.netflix.com/nz/title/80057281)
    via Plex's availabilities endpoint, falling back to Netflix search.
    """
    with db_session() as conn:
        mrow = conn.execute(
            "SELECT id, title, year, media_type, discover_rating_key FROM media_items WHERE id = ?",
            (media_id,),
        ).fetchone()
        if not mrow:
            return "https://www.netflix.com"
        srow = conn.execute(
            "SELECT id, external_url FROM media_sources WHERE media_id = ? AND machine_id = ?",
            (media_id, NETFLIX_MACHINE_ID),
        ).fetchone()

    if srow and srow["external_url"] and srow["external_url"].startswith("https://www.netflix.com/"):
        return str(srow["external_url"])

    plex_token = get_setting("plex_token")
    drk = mrow["discover_rating_key"]
    direct_url = ""

    if plex_token:
        async with httpx.AsyncClient(timeout=8.0) as client:
            if not drk:
                resolved = await resolve_discover_rating_key(
                    client, plex_token, mrow["title"], mrow["year"], mrow["media_type"]
                )
                if resolved and resolved.get("ratingKey"):
                    drk = str(resolved["ratingKey"])
                    with db_session() as conn:
                        conn.execute(
                            "UPDATE media_items SET discover_rating_key = ? WHERE id = ?",
                            (drk, media_id),
                        )

            if drk:
                try:
                    resp = await client.get(
                        f"{PLEX_METADATA_BASE}/library/metadata/{drk}/availabilities",
                        headers=plex_headers(token=plex_token),
                    )
                    if resp.status_code == 200:
                        avails = resp.json().get("MediaContainer", {}).get("Availability") or []
                        for av in avails:
                            if str(av.get("platform") or "").lower() == "netflix":
                                direct_url = str(
                                    av.get("url")
                                    or av.get("platformUrl")
                                    or av.get("platformInfo", {}).get("web", {}).get("url")
                                    or ""
                                )
                                if direct_url:
                                    break
                except Exception as exc:
                    logger.warning("Availability lookup warning for %s: %s", mrow["title"], exc)

    if direct_url and srow:
        with db_session() as conn:
            conn.execute(
                "UPDATE media_sources SET external_url = ? WHERE id = ?",
                (direct_url, int(srow["id"])),
            )
        return direct_url

    return f"https://www.netflix.com/search?q={quote(str(mrow['title']))}"


def _parse_netflix_date(raw_date: str, prefer_dmy: bool = True) -> int | None:
    s = (raw_date or "").strip()
    if not s:
        return None
    # Strip trailing time if ISO/GDPR format
    date_part = s.split(" ")[0].split("T")[0]
    formats = (
        ["%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"]
        if prefer_dmy
        else ["%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"]
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(date_part, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


def parse_netflix_csv_rows(
    csv_text: str,
    prefer_dmy: bool = True,
    profile_filter: str | None = None,
) -> dict[str, Any]:
    """
    Parse NetflixViewingActivity.csv (or GDPR ViewingActivity.csv) into canonical watched works.
    Automatically rolls episode rows up into TV shows and counts watched episodes vs movies.
    """
    cleaned = csv_text.lstrip("\ufeff").strip()
    if not cleaned:
        raise ValueError("The uploaded CSV file is empty.")

    reader = csv.DictReader(io.StringIO(cleaned))
    if not reader.fieldnames:
        raise ValueError("Could not read CSV headers. Upload NetflixViewingActivity.csv from netflix.com/viewingactivity.")

    norm_headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    title_col = norm_headers.get("title")
    date_col = norm_headers.get("date") or norm_headers.get("start time")
    supp_col = norm_headers.get("supplemental video type")
    prof_col = norm_headers.get("profile name")

    if not title_col:
        raise ValueError("CSV must contain a 'Title' column (standard NetflixViewingActivity.csv).")

    raw_rows: list[tuple[str, int | None]] = []
    profiles_seen: set[str] = set()

    for row in reader:
        if prof_col and row.get(prof_col):
            p_val = row[prof_col].strip()
            profiles_seen.add(p_val)
            if profile_filter and p_val.lower() != profile_filter.strip().lower():
                continue

        # Skip trailers, hooks, teasers in GDPR exports
        if supp_col and (row.get(supp_col) or "").strip():
            continue

        raw_title = (row.get(title_col) or "").strip()
        if not raw_title:
            continue
        low_t = raw_title.lower()
        if any(skip in low_t for skip in ("(trailer)", "_hook_", "teaser:", "season recap:")):
            continue

        ts = _parse_netflix_date(row.get(date_col, "") if date_col else "", prefer_dmy=prefer_dmy)
        raw_rows.append((raw_title, ts))

    # First pass: detect anthology/colon-delimited shows where "Prefix: Episode" appears >= 3 times
    colon_prefix_distinct_suffixes: dict[str, set[str]] = defaultdict(set)
    for raw_title, _ in raw_rows:
        if ":" in raw_title and not EPISODE_SPLIT_RE.match(raw_title):
            prefix, suffix = raw_title.split(":", 1)
            if len(prefix.strip()) >= 2 and len(suffix.strip()) >= 2:
                colon_prefix_distinct_suffixes[prefix.strip()].add(suffix.strip().lower())

    anthology_prefixes = {
        pref for pref, suffixes in colon_prefix_distinct_suffixes.items() if len(suffixes) >= 3
    }

    # Aggregate into canonical works
    aggregated: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_title, ts in raw_rows:
        m = EPISODE_SPLIT_RE.match(raw_title)
        if m:
            work_title = m.group("show").strip()
            mtype = "show"
        else:
            matched_pref = None
            if ":" in raw_title:
                pref = raw_title.split(":", 1)[0].strip()
                if pref in anthology_prefixes:
                    matched_pref = pref
            if matched_pref:
                work_title = matched_pref
                mtype = "show"
            else:
                work_title = raw_title
                mtype = "movie"

        norm_key = normalize_title_key(work_title)
        if not norm_key:
            continue

        bucket_key = (mtype, norm_key)
        if bucket_key not in aggregated:
            aggregated[bucket_key] = {
                "title": work_title,
                "media_type": mtype,
                "count": 0,
                "dates": [],
            }
        aggregated[bucket_key]["count"] += 1
        if ts:
            aggregated[bucket_key]["dates"].append(ts)

    return {
        "rows_parsed": len(raw_rows),
        "works": list(aggregated.values()),
        "profiles_seen": sorted(profiles_seen),
    }


async def import_netflix_viewing_csv(
    csv_text: str,
    profile_filter: str | None = None,
) -> dict[str, Any]:
    region = get_setting("watch_region", "NZ").upper()
    prefer_dmy = region not in ("US", "PH")
    parsed = parse_netflix_csv_rows(csv_text, prefer_dmy=prefer_dmy, profile_filter=profile_filter)
    works = parsed["works"]
    if not works:
        return {
            "rows_parsed": parsed["rows_parsed"],
            "unique_titles": 0,
            "matched_existing": 0,
            "newly_enriched": 0,
            "movies_marked": 0,
            "shows_marked": 0,
            "abandoned_detected": 0,
        }

    # Sort by most watched / most recent first so the strongest signals are enriched first
    works.sort(
        key=lambda w: (w["count"], max(w["dates"]) if w["dates"] else 0),
        reverse=True,
    )

    now_ts = int(time.time())
    abandoned_cutoff = now_ts - 21 * 86400

    with db_session() as conn:
        by_type_norm: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        by_any_norm: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in conn.execute(
            "SELECT id, media_type, title, original_title, leaf_count, is_watched, max_view_count, viewed_leaf_count FROM media_items"
        ).fetchall():
            d = dict(r)
            nt = normalize_title_key(d["title"])
            by_type_norm[(d["media_type"], nt)].append(d)
            by_any_norm[nt].append(d)
            if d.get("original_title"):
                ont = normalize_title_key(d["original_title"])
                by_type_norm[(d["media_type"], ont)].append(d)
                by_any_norm[ont].append(d)

    matched_updates: list[tuple[int, dict[str, Any], int]] = []
    unmatched_works: list[dict[str, Any]] = []

    for w in works:
        nt = normalize_title_key(w["title"])
        candidates = by_type_norm.get((w["media_type"], nt)) or by_any_norm.get(nt) or []
        if candidates:
            target = candidates[0]
            matched_updates.append((int(target["id"]), w, int(target.get("leaf_count") or 0)))
        else:
            unmatched_works.append(w)

    # Resolve top unmatched Netflix history titles via Plex Discover + batch Metadata so they enter the Taste Graph with full Directors/Writers/Genres!
    newly_enriched = 0
    plex_token = get_setting("plex_token")
    if plex_token and unmatched_works:
        sem = asyncio.Semaphore(8)
        to_resolve = unmatched_works[:160]

        async with httpx.AsyncClient(timeout=12.0) as client:
            async def resolve_one(w: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
                async with sem:
                    try:
                        md = await resolve_discover_rating_key(
                            client, plex_token, w["title"], None, w["media_type"]
                        )
                        return w, md
                    except Exception:
                        return w, None

            resolved_pairs = await asyncio.gather(*[resolve_one(w) for w in to_resolve])
            rk_to_work: dict[str, dict[str, Any]] = {}
            for w, md in resolved_pairs:
                if md and md.get("ratingKey"):
                    rk_to_work[str(md["ratingKey"])] = w

            rks = list(rk_to_work.keys())
            chunks = [rks[i : i + 35] for i in range(0, len(rks), 35)]
            enriched_mds: list[dict[str, Any]] = []
            for chunk in chunks:
                try:
                    resp = await client.get(
                        f"{PLEX_METADATA_BASE}/library/metadata/{','.join(chunk)}",
                        headers=plex_headers(token=plex_token),
                    )
                    if resp.status_code == 200:
                        enriched_mds.extend(
                            resp.json().get("MediaContainer", {}).get("Metadata") or []
                        )
                except Exception:
                    pass

        if enriched_mds:
            with db_session() as conn:
                existing_by_ckey = {
                    r["canonical_key"]: int(r["id"])
                    for r in conn.execute("SELECT id, canonical_key FROM media_items").fetchall()
                }
                existing_by_drk = {
                    str(r["discover_rating_key"]): int(r["id"])
                    for r in conn.execute(
                        "SELECT id, discover_rating_key FROM media_items WHERE discover_rating_key IS NOT NULL"
                    ).fetchall()
                }
                existing_by_title_yr = {
                    (r["media_type"], normalize_title_key(r["title"]), int(r["year"] or 0)): int(r["id"])
                    for r in conn.execute("SELECT id, media_type, title, year FROM media_items").fetchall()
                }

                for md in enriched_mds:
                    rk = str(md.get("ratingKey") or "")
                    w = rk_to_work.get(rk)
                    if not rk or not w:
                        continue
                    mtype = "movie" if md.get("type") == "movie" else "show"
                    duration_ms = int(md.get("duration") or 0)
                    duration_min = round(duration_ms / 60000) if duration_ms >= 60000 else None
                    thumb = str(md.get("thumb") or "")
                    mid = _upsert_streaming_catalog_item(
                        conn,
                        existing_by_ckey,
                        existing_by_drk,
                        existing_by_title_yr,
                        canonical_key=f"plex:{mtype}:{rk}",
                        media_type=mtype,
                        plex_guid=str(md.get("guid") or f"plex://{mtype}/{rk}"),
                        discover_rk=rk,
                        tmdb_id=None,
                        title=str(md.get("title") or w["title"]),
                        year=int(md["year"]) if md.get("year") else None,
                        tagline=str(md.get("tagline") or ""),
                        summary=str(md.get("summary") or ""),
                        content_rating=str(md.get("contentRating") or ""),
                        duration_min=duration_min,
                        critic_rating=float(md["rating"]) if md.get("rating") is not None else None,
                        audience_rating=float(md["audienceRating"]) if md.get("audienceRating") is not None else None,
                        genres=_extract_tags(md, "Genre", 8),
                        directors=_extract_tags(md, "Director", 5),
                        writers=_extract_tags(md, "Writer", 5),
                        cast=_extract_tags(md, "Role", 8),
                        countries=_extract_tags(md, "Country", 4),
                        studios=[str(md["studio"]).strip()] if md.get("studio") else [],
                        poster_url_external=thumb if thumb.startswith("http") else None,
                        cloud_watched=True,
                        watchlist_keys=set(),
                    )
                    # Mark external_only=1 if no local/shared/Netflix source row points to it yet
                    has_src = conn.execute(
                        "SELECT 1 FROM media_sources WHERE media_id = ?", (mid,)
                    ).fetchone()
                    if not has_src:
                        conn.execute(
                            "UPDATE media_items SET is_external_only = 1 WHERE id = ?", (mid,)
                        )
                    leaf_cnt = int(md.get("leafCount") or 0)
                    if leaf_cnt > 0:
                        conn.execute(
                            "UPDATE media_items SET leaf_count = MAX(leaf_count, ?) WHERE id = ?",
                            (leaf_cnt, mid),
                        )
                    matched_updates.append((mid, w, leaf_cnt))
                    newly_enriched += 1

    movies_marked = 0
    shows_marked = 0
    abandoned_detected = 0

    with db_session() as conn:
        for mid, w, leaf_cnt in matched_updates:
            cnt = int(w["count"])
            latest_ts = max(w["dates"]) if w["dates"] else now_ts
            is_aband = 0
            if w["media_type"] == "show":
                shows_marked += 1
                if cnt == 1 and (leaf_cnt == 0 or leaf_cnt >= 4) and latest_ts < abandoned_cutoff:
                    is_aband = 1
                    abandoned_detected += 1
            else:
                movies_marked += 1

            conn.execute(
                """
                UPDATE media_items SET
                    is_watched = 1,
                    netflix_watched_count = MAX(netflix_watched_count, ?),
                    netflix_abandoned = ?,
                    netflix_last_viewed_at = COALESCE(MAX(COALESCE(netflix_last_viewed_at, 0), ?), ?),
                    last_viewed_at = MAX(COALESCE(last_viewed_at, 0), ?),
                    is_abandoned = CASE WHEN max_view_count = 0 AND viewed_leaf_count < 3 AND ? = 1 THEN 1 ELSE is_abandoned END
                WHERE id = ?
                """,
                (cnt, is_aband, latest_ts, latest_ts, latest_ts, is_aband, mid),
            )
        conn.execute("DELETE FROM llm_cache")

    return {
        "rows_parsed": parsed["rows_parsed"],
        "unique_titles": len(works),
        "matched_existing": len(matched_updates) - newly_enriched,
        "newly_enriched": newly_enriched,
        "movies_marked": movies_marked,
        "shows_marked": shows_marked,
        "abandoned_detected": abandoned_detected,
        "profiles_seen": parsed["profiles_seen"],
    }
