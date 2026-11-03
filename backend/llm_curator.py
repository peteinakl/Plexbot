from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx

from .db import db_session, get_all_settings, hydrate_media_row
from .plex_client import (
    PLEX_METADATA_BASE,
    build_plex_deep_link,
    get_setting,
    plex_headers,
    resolve_discover_rating_key,
    upsert_discover_item,
)

logger = logging.getLogger("plexbot.llm")

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
}


def get_active_llm_config() -> dict[str, Any]:
    s = get_all_settings()
    provider = s.get("llm_provider", "none")
    if provider not in ("gemini", "anthropic", "openai"):
        return {"enabled": False, "provider": "none", "model": "", "has_key": False}

    key_map = {
        "gemini": s.get("gemini_api_key", ""),
        "anthropic": s.get("anthropic_api_key", ""),
        "openai": s.get("openai_api_key", ""),
    }
    model_map = {
        "gemini": s.get("gemini_model") or DEFAULT_MODELS["gemini"],
        "anthropic": s.get("anthropic_model") or DEFAULT_MODELS["anthropic"],
        "openai": s.get("openai_model") or DEFAULT_MODELS["openai"],
    }
    api_key = key_map[provider].strip()
    return {
        "enabled": bool(api_key),
        "provider": provider,
        "model": model_map[provider],
        "api_key": api_key,
        "has_key": bool(api_key),
    }


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            return json.loads(m.group(0))
        raise


async def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 40.0,
) -> dict[str, Any]:
    cfg = get_active_llm_config()
    prov = provider or cfg["provider"]
    key = (api_key or cfg.get("api_key") or "").strip()
    mdl = (model or cfg.get("model") or DEFAULT_MODELS.get(prov, "")).strip()

    if not key or prov not in ("gemini", "anthropic", "openai"):
        raise ValueError("No active LLM API key configured. Add a Gemini, Claude, or OpenAI key in Settings.")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if prov == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
            resp = await client.post(
                url,
                params={"key": key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": 0.45,
                        "responseMimeType": "application/json",
                    },
                },
            )
            if resp.status_code >= 400:
                raise ValueError(f"Gemini API error ({resp.status_code}): {resp.text[:280]}")
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "{}")
            )
            return _extract_json_object(text)

        if prov == "anthropic":
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": mdl,
                    "max_tokens": 2800,
                    "temperature": 0.45,
                    "system": system_prompt + "\n\nRespond with a single valid JSON object only, no prose outside JSON.",
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            if resp.status_code >= 400:
                raise ValueError(f"Anthropic API error ({resp.status_code}): {resp.text[:280]}")
            data = resp.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return _extract_json_object(text)

        # OpenAI
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": mdl,
                "temperature": 0.45,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        if resp.status_code >= 400:
            raise ValueError(f"OpenAI API error ({resp.status_code}): {resp.text[:280]}")
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return _extract_json_object(text)


async def test_llm_connection(provider: str, api_key: str, model: str) -> dict[str, Any]:
    res = await call_llm_json(
        system_prompt="Return JSON: {\"ok\": true, \"greeting\": \"short cinephile hello\"}",
        user_prompt="Ping test.",
        provider=provider,
        api_key=api_key,
        model=model,
        timeout=18.0,
    )
    return {"ok": True, "provider": provider, "model": model, "message": res.get("greeting", "Connected!")}


async def curate_with_llm(
    base_recommendations: list[dict[str, Any]],
    dna: dict[str, Any],
    profile_name: str,
    profile_id: str,
    mood: str,
    prompt: str,
    include_outside: bool,
    discovery_level: float,
    media_type: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cfg = get_active_llm_config()
    if not cfg["enabled"]:
        raise ValueError("Configure a Gemini, Anthropic, or OpenAI API key in Settings to use AI Deep Curate.")

    shortlist = base_recommendations[:42]
    cand_sig = ",".join(str(it["id"]) for it in shortlist[:25])
    raw_key = json.dumps(
        {
            "prov": cfg["provider"],
            "mdl": cfg["model"],
            "prof": profile_id,
            "mood": mood,
            "prompt": prompt.strip().lower(),
            "out": include_outside,
            "disc": round(discovery_level, 1),
            "mtype": media_type,
            "sig": cand_sig,
        },
        sort_keys=True,
    )
    cache_key = "curate:v2:" + hashlib.sha256(raw_key.encode()).hexdigest()[:24]

    if not force_refresh:
        with db_session() as conn:
            cached = conn.execute(
                "SELECT payload_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            if cached:
                try:
                    return json.loads(cached["payload_json"])
                except Exception:
                    pass

    compact_candidates = [
        {
            "id": it["id"],
            "title": it["title"],
            "year": it.get("year"),
            "type": it["media_type"],
            "min": it.get("duration_min"),
            "genres": it.get("genres", [])[:4],
            "directors": it.get("directors", [])[:2],
            "writers": it.get("writers", [])[:2],
            "cast": it.get("cast", [])[:3],
            "rating": it.get("audience_rating") or it.get("critic_rating"),
            "plot": (it.get("summary") or "")[:200],
        }
        for it in shortlist
    ]

    taste_summary = {
        "viewer_mode": profile_name,
        "favorites_and_completed": [
            f"{a['title']} ({a.get('year') or ''}) [{a['reason']}]"
            for a in dna.get("anchor_favorites", [])[:16]
        ],
        "disliked_or_abandoned": [
            f"{a['title']} ({a.get('year') or ''}) [{a['reason']}]"
            for a in dna.get("avoid_examples", [])[:10]
        ],
        "favorite_directors": [x["name"] for x in dna.get("top_directors", [])[:6]],
        "favorite_writers": [x["name"] for x in dna.get("top_writers", [])[:5]],
        "genre_pairings": [x["name"] for x in dna.get("top_pairings", [])[:5]],
        "recurring_themes": [x["name"] for x in dna.get("top_themes", [])[:8]],
    }

    system_prompt = (
        "You are Plexbot, an incisive, zero-hype film and television curator. "
        "Unlike Netflix's promotional algorithms, you never push lowest-common-denominator filler or marketing fluff. "
        "You read between the lines of what a viewer genuinely finished, rewatched, rated, or abandoned — "
        "noticing tone, writing sharpness, pacing, moral complexity, atmosphere, and craft.\n\n"
        "Return STRICT JSON matching this exact schema:\n"
        "{\n"
        '  "curator_headline": "1-sentence tailored framing for this exact mood/viewer",\n'
        '  "picks": [\n'
        '    {"id": 123, "match_score": 95, "vibe_tag": "2-4 word micro-tone", "pitch": "Specific 1-2 sentence spoiler-free reason connecting directly to their loved titles & tonight\'s request"}\n'
        "  ],\n"
        '  "outside_discoveries": [\n'
        '    {"title": "Exact Title", "year": 2019, "media_type": "movie", "match_score": 93, "vibe_tag": "2-4 word micro-tone", "pitch": "Specific 1-2 sentence reason"}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "1. Select 12 to 16 best items in `picks` using ONLY exact integer `id`s from `playable_candidates`.\n"
        "2. Respect `mood`, `user_request`, `media_type_filter`, and `discovery_preference` (0=familiar classics, 1=deep-cut hidden gems).\n"
        "3. Never spoil twists. Reference 1-2 specific watched titles where natural so the user sees WHY it fits.\n"
        "4. Populate `outside_discoveries` ONLY if `allow_outside_discoveries` is true (up to 5 brilliant titles NOT in `playable_candidates` and NOT in `favorites_and_completed`); otherwise return `[]`."
    )

    user_payload = json.dumps(
        {
            "viewer_taste": taste_summary,
            "mood": mood,
            "user_request": prompt or "Give me genuinely great recommendations tailored to my taste.",
            "media_type_filter": media_type,
            "discovery_preference": round(discovery_level, 2),
            "allow_outside_discoveries": include_outside,
            "playable_candidates": compact_candidates,
        },
        ensure_ascii=False,
    )

    llm_out = await call_llm_json(system_prompt=system_prompt, user_prompt=user_payload)

    by_id = {int(it["id"]): dict(it) for it in base_recommendations}
    curated_items: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for p in llm_out.get("picks") or []:
        try:
            cid = int(p["id"])
        except Exception:
            continue
        if cid not in by_id or cid in used_ids:
            continue
        used_ids.add(cid)
        item = dict(by_id[cid])
        if p.get("match_score"):
            item["match_score"] = max(65, min(99, int(p["match_score"])))
        if p.get("pitch"):
            item["explanation"] = str(p["pitch"]).strip()
        if p.get("vibe_tag"):
            item["vibe_tag"] = str(p["vibe_tag"]).strip()
        item["ai_curated"] = True
        curated_items.append(item)

    # Resolve outside discoveries via Plex's global Discover catalog so they get real posters & 1-click Watchlist!
    if include_outside and llm_out.get("outside_discoveries"):
        plex_token = get_setting("plex_token")
        if plex_token:
            async with httpx.AsyncClient(timeout=12.0) as client:
                for ext in (llm_out.get("outside_discoveries") or [])[:5]:
                    ext_title = str(ext.get("title") or "").strip()
                    ext_year = int(ext["year"]) if ext.get("year") else None
                    ext_type = "show" if str(ext.get("media_type")).lower() in ("show", "tv", "series") else "movie"
                    if not ext_title:
                        continue
                    try:
                        md = await resolve_discover_rating_key(
                            client, plex_token, ext_title, ext_year, ext_type
                        )
                        if not md:
                            continue
                        rk = str(md.get("ratingKey") or "")
                        if rk:
                            d_resp = await client.get(
                                f"{PLEX_METADATA_BASE}/library/metadata/{rk}",
                                headers=plex_headers(token=plex_token),
                            )
                            if d_resp.status_code == 200:
                                full_md = d_resp.json().get("MediaContainer", {}).get("Metadata") or []
                                if full_md:
                                    md = full_md[0]
                        mid = await upsert_discover_item(md)
                        if mid in used_ids:
                            continue
                        with db_session() as conn:
                            mrow = conn.execute("SELECT * FROM media_items WHERE id = ?", (mid,)).fetchone()
                            if not mrow or mrow["is_watched"]:
                                continue
                            srcs = []
                            for s in conn.execute(
                                """
                                SELECT ms.*, sv.name AS server_name, sv.owned, sv.owner_name, sv.online, sv.latency_ms, sv.source_type
                                FROM media_sources ms
                                JOIN servers sv ON sv.machine_id = ms.machine_id
                                WHERE ms.media_id = ? AND sv.enabled = 1
                                """,
                                (mid,),
                            ).fetchall():
                                sd = dict(s)
                                if (sd.get("source_type") or "plex") == "streaming":
                                    sd["deep_link"] = sd.get("external_url") or f"/api/netflix/open/{mid}"
                                else:
                                    sd["deep_link"] = build_plex_deep_link(sd["machine_id"], sd["rating_key"])
                                srcs.append(sd)

                        hydrated = hydrate_media_row(mrow, sources=srcs, feedback_sentiment=None)
                        hydrated["match_score"] = max(70, min(98, int(ext.get("match_score") or 90)))
                        hydrated["explanation"] = str(ext.get("pitch") or "Recommended outside discovery.").strip()
                        hydrated["vibe_tag"] = str(ext.get("vibe_tag") or "Outside Discovery").strip()
                        hydrated["because_you_liked"] = []
                        hydrated["match_reasons"] = [hydrated["vibe_tag"]]
                        hydrated["ai_curated"] = True
                        used_ids.add(mid)
                        curated_items.append(hydrated)
                    except Exception as exc:
                        logger.warning("Could not resolve outside discovery %s: %s", ext_title, exc)

    # Append remaining strong local picks after AI-curated top picks so scrolling still has depth
    for it in base_recommendations:
        if int(it["id"]) not in used_ids and len(curated_items) < 28:
            curated_items.append(it)

    result_payload = {
        "curator_headline": str(llm_out.get("curator_headline") or ""),
        "provider": cfg["provider"],
        "model": cfg["model"],
        "items": curated_items,
    }

    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, profile_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (cache_key, profile_id, json.dumps(result_payload), int(time.time())),
        )

    return result_payload


async def generate_taste_portrait(
    profile_id: str,
    profile_name: str,
    dna: dict[str, Any],
    force_refresh: bool = False,
) -> dict[str, Any]:
    cfg = get_active_llm_config()
    if not cfg["enabled"]:
        raise ValueError("Configure an LLM API key in Settings to generate an AI Taste Portrait.")

    fav_sig = ",".join(str(a["id"]) for a in dna.get("anchor_favorites", [])[:15])
    avoid_sig = ",".join(str(a["id"]) for a in dna.get("avoid_examples", [])[:10])
    cache_key = "portrait:" + hashlib.sha256(
        f"{cfg['provider']}:{cfg['model']}:{profile_id}:{fav_sig}:{avoid_sig}".encode()
    ).hexdigest()[:24]

    if not force_refresh:
        with db_session() as conn:
            row = conn.execute(
                "SELECT payload_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            if row:
                return json.loads(row["payload_json"])

    system_prompt = (
        "You are a perceptive cinema & TV critic profiling a viewer's real sensibility from their watch history. "
        "Avoid generic horoscopes. Pinpoint specific through-lines in writing, pacing, atmosphere, and themes.\n"
        "Return STRICT JSON:\n"
        "{\n"
        '  "archetype": "3-5 word evocative taste title",\n'
        '  "summary": "2 concise, insightful paragraphs explaining what genuinely hooks them vs what loses them",\n'
        '  "sweet_spots": ["3 specific micro-genres or sensibilities they love"],\n'
        '  "stretch_ideas": ["2 intriguing adjacent directions they would likely love exploring next"]\n'
        "}"
    )

    portrait = await call_llm_json(
        system_prompt=system_prompt,
        user_prompt=json.dumps({"profile": profile_name, "taste_dna": dna}, ensure_ascii=False),
    )
    portrait["provider"] = cfg["provider"]
    portrait["model"] = cfg["model"]

    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, profile_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (cache_key, profile_id, json.dumps(portrait), int(time.time())),
        )
    return portrait
