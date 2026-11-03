from __future__ import annotations

import itertools
import json
import math
import re
import time
from collections import Counter, defaultdict
from typing import Any

from .db import db_session, hydrate_media_row, json_loads_list
from .plex_client import build_plex_deep_link

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "his", "her", "they", "their",
    "into", "who", "when", "where", "what", "which", "after", "before", "about", "over",
    "under", "between", "through", "during", "without", "within", "along", "following",
    "across", "behind", "beyond", "plus", "except", "but", "not", "only", "own", "same",
    "so", "than", "too", "very", "can", "will", "just", "should", "now", "are", "was",
    "were", "been", "being", "have", "has", "had", "having", "does", "did", "doing",
    "one", "two", "three", "new", "old", "young", "man", "woman", "men", "women",
    "life", "lives", "world", "story", "film", "movie", "series", "show", "season",
    "years", "year", "time", "day", "days", "way", "find", "finds", "found", "must",
    "take", "takes", "make", "makes", "made", "get", "gets", "back", "soon", "become",
    "becomes", "begins", "begin", "set", "sets", "discover", "discovers", "learn",
    "learns", "try", "tries", "help", "helps", "turn", "turns", "left", "right",
    "home", "family", "friends", "friend", "people", "group", "team", "everything",
    "something", "nothing", "anything", "someone", "everyone", "himself", "herself",
    "themselves", "each", "other", "another", "while", "whose", "there", "here",
    "however", "meanwhile", "together", "apart", "force", "forced", "forces", "face",
    "faces", "lead", "leads", "living", "named", "known", "called", "based", "true",
    "events", "tells", "follow", "follows", "around", "against", "upon", "onto",
}

MOOD_DEFINITIONS: dict[str, dict[str, Any]] = {
    "gripping": {
        "label": "Gripping & Tense",
        "boost_genres": {"Thriller", "Mystery", "Crime", "Suspense"},
        "penalize_genres": {"Family", "Children", "Musical"},
        "keywords": {
            "conspiracy", "detective", "investigation", "hostage", "espionage", "heist",
            "murder", "suspect", "manhunt", "kidnapped", "undercover", "cartel", "tense",
            "paranoia", "blackmail", "interrogation", "witness", "assassin",
        },
    },
    "mind_bending": {
        "label": "Smart & Mind-Bending",
        "boost_genres": {"Science Fiction", "Sci-Fi", "Mystery", "Psychological", "Thriller"},
        "penalize_genres": {"Reality", "Game Show", "Talk Show"},
        "keywords": {
            "reality", "memory", "consciousness", "simulation", "paradox", "quantum",
            "parallel", "time", "artificial", "intelligence", "dream", "illusion",
            "dystopian", "experiment", "alien", "dimension", "clone", "psychological",
        },
    },
    "funny": {
        "label": "Sharp & Funny",
        "boost_genres": {"Comedy"},
        "penalize_genres": {"Horror", "War"},
        "keywords": {
            "hilarious", "satire", "witty", "absurd", "misfit", "awkward", "comedic",
            "mockumentary", "eccentric", "chaotic", "scheme", "deadpan", "parody",
        },
    },
    "weeknight": {
        "label": "Easy Weeknight (<105m)",
        "boost_genres": {"Comedy", "Mystery", "Thriller", "Animation", "Crime"},
        "penalize_genres": set(),
        "max_movie_min": 108,
        "max_show_min": 42,
        "keywords": {"fast", "tight", "clever", "wit", "heist", "mystery"},
    },
    "epic": {
        "label": "Epic & Immersive",
        "boost_genres": {"Adventure", "Science Fiction", "Sci-Fi", "Fantasy", "History", "War", "Drama", "Western"},
        "penalize_genres": {"Reality"},
        "min_movie_min": 120,
        "keywords": {
            "empire", "kingdom", "expedition", "odyssey", "dynasty", "frontier",
            "galaxy", "rebellion", "epic", "civilization", "voyage", "epic", "planet",
        },
    },
    "comfort": {
        "label": "Warm & Comforting",
        "boost_genres": {"Comedy", "Romance", "Animation", "Adventure", "Family", "Music"},
        "penalize_genres": {"Horror", "War"},
        "keywords": {
            "charming", "warm", "heartfelt", "friendship", "bakery", "chef", "summer",
            "town", "music", "journey", "magical", "gentle", "kindness", "road",
        },
    },
    "dark": {
        "label": "Dark & Gritty",
        "boost_genres": {"Crime", "Thriller", "Horror", "Mystery", "Drama", "Film-Noir", "Western"},
        "penalize_genres": {"Family", "Children", "Musical"},
        "keywords": {
            "noir", "corrupt", "brutal", "revenge", "underworld", "grisly", "bleak",
            "obsessive", "serial", "killer", "syndicate", "occult", "vengeance", "gritty",
        },
    },
    "hidden_gems": {
        "label": "Hidden Gems",
        "boost_genres": set(),
        "penalize_genres": set(),
        "force_discovery": 0.85,
        "min_quality": 7.3,
        "keywords": set(),
    },
}


def extract_theme_tokens(text: str, max_tokens: int = 16) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[a-z]{4,18}", text.lower())
    filtered = [w for w in words if w not in STOPWORDS]
    # Keep distinct informative words preserving order
    seen: set[str] = set()
    out: list[str] = []
    for w in filtered:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_tokens:
            break
    return out


def extract_item_features(row: dict[str, Any]) -> dict[str, float]:
    """
    Build unweighted raw feature weights for a media item across auteurs, writers,
    cast, studios, genres, genre-pairings, era, origin country, and plot themes.
    """
    feats: dict[str, float] = {}
    genres = json_loads_list(row.get("genres_json"))
    directors = json_loads_list(row.get("directors_json"))
    writers = json_loads_list(row.get("writers_json"))
    cast = json_loads_list(row.get("cast_json"))
    countries = json_loads_list(row.get("countries_json"))
    studios = json_loads_list(row.get("studios_json"))
    collections = json_loads_list(row.get("collections_json"))

    for d in directors[:4]:
        feats[f"dir:{d}"] = 2.45
    for w in writers[:4]:
        feats[f"wri:{w}"] = 2.10
    for idx, actor in enumerate(cast[:6]):
        feats[f"cast:{actor}"] = 1.35 if idx < 3 else 0.72
    for st in studios[:2]:
        feats[f"studio:{st}"] = 1.25
    for col in collections[:2]:
        feats[f"col:{col}"] = 1.40

    clean_genres = sorted(set(genres[:5]))
    for g in clean_genres:
        feats[f"genre:{g}"] = 0.92
    for g1, g2 in itertools.combinations(clean_genres[:4], 2):
        feats[f"gpair:{g1}+{g2}"] = 1.32

    year = row.get("year")
    if year and isinstance(year, int) and year >= 1920:
        decade = f"{(year // 10) * 10}s"
        feats[f"decade:{decade}"] = 0.60

    for c in countries[:2]:
        if c not in ("United States of America", "USA", "US"):
            feats[f"country:{c}"] = 0.95
        else:
            feats[f"country:US"] = 0.25

    blob = f"{row.get('tagline') or ''} {row.get('summary') or ''}"
    for tok in extract_theme_tokens(blob, max_tokens=14):
        feats[f"theme:{tok}"] = 0.88

    return feats


def compute_item_signal_weight(
    row: dict[str, Any],
    profile_id: str,
    inherit_shared: bool,
    feedback_by_profile: dict[str, dict[int, str]],
    now_ts: int,
) -> tuple[float, str]:
    """
    Returns (weight, signal_reason) for how strongly an item influences the profile's taste.
    Positive = loved/liked/completed; Negative = disliked/abandoned.
    """
    mid = int(row["id"])
    prof_fb = feedback_by_profile.get(profile_id, {}).get(mid)

    sentiment_weights = {
        "love": (2.65, "Loved"),
        "like": (1.50, "Liked"),
        "meh": (-0.40, "Meh"),
        "dislike": (-2.15, "Disliked"),
        "dismiss": (0.0, "Dismissed"),
        "seen_unrated": (0.0, "Marked Seen"),
    }

    if prof_fb in sentiment_weights:
        return sentiment_weights[prof_fb]

    # Special household blend for "together" profile: combine individual overrides!
    if profile_id == "together":
        sub_weights: list[float] = []
        for sub_p in ("me", "partner"):
            s_fb = feedback_by_profile.get(sub_p, {}).get(mid)
            if s_fb in sentiment_weights:
                # A strong dislike from either partner weighs heavily against joint movie night!
                w, _ = sentiment_weights[s_fb]
                sub_weights.append(w * 1.25 if w < 0 else w)
        if sub_weights:
            avg_w = sum(sub_weights) / len(sub_weights)
            return avg_w, "Household Blend"

    if not inherit_shared:
        return 0.0, ""

    if not row.get("is_watched"):
        return 0.0, ""

    # Check Plex native 0-10 star rating if present
    ur = row.get("max_user_rating")
    if ur is not None:
        ur_f = float(ur)
        if ur_f >= 9.0:
            return 2.20, f"Plex ★ {ur_f:.0f}/10"
        if ur_f >= 7.5:
            return 1.40, f"Plex ★ {ur_f:.1f}/10"
        if ur_f >= 6.0:
            return 0.55, f"Plex ★ {ur_f:.0f}/10"
        if ur_f <= 4.5:
            return -1.55, f"Low Plex Rating ({ur_f:.0f}/10)"

    if row.get("is_abandoned"):
        return -0.85, "Abandoned partway"

    recency_bonus = 0.0
    lv = row.get("last_viewed_at")
    if lv and (now_ts - int(lv)) < 180 * 86400:
        recency_bonus = 0.15

    if row.get("media_type") == "movie":
        vc = int(row.get("max_view_count") or 0)
        if vc >= 3:
            return 1.90 + recency_bonus, f"Rewatched {vc}x"
        if vc == 2:
            return 1.45 + recency_bonus, "Rewatched 2x"
        if vc == 1:
            return 0.82 + recency_bonus, "Watched"
    else:
        leaves = int(row.get("leaf_count") or 0)
        viewed = int(row.get("viewed_leaf_count") or 0)
        ratio = (viewed / leaves) if leaves > 0 else 0.0
        if (leaves >= 4 and ratio >= 0.85) or viewed >= 16:
            return 1.65 + recency_bonus, f"Completed {viewed} eps"
        if ratio >= 0.50 or viewed >= 6:
            return 1.12 + recency_bonus, f"Watched {viewed} eps"
        if viewed >= 3 or int(row.get("max_view_count") or 0) >= 1:
            return 0.70 + recency_bonus, "Watched"

    return 0.0, ""


def compute_quality_prior(critic: float | None, audience: float | None) -> float:
    """
    Non-commercial Bayesian quality score on [0.0, 1.0].
    Uses audience + critic ratings with shrinkage toward 6.8 so obscure titles aren't penalized,
    while genuinely acclaimed works rise and poorly-received cash-grabs sink.
    """
    scores: list[tuple[float, float]] = []
    if audience is not None and audience > 0:
        scores.append((float(audience), 1.3))
    if critic is not None and critic > 0:
        scores.append((float(critic), 1.0))
    if not scores:
        return 0.62
    weighted = sum(s * w for s, w in scores) / sum(w for _, w in scores)
    # Shrink slightly toward 6.8
    shrunk = 0.82 * weighted + 0.18 * 6.8
    return max(0.05, min(1.0, (shrunk - 4.0) / 5.5))


def human_feature_label(feat: str) -> str:
    prefix, val = feat.split(":", 1)
    if prefix == "dir":
        return f"Dir. {val}"
    if prefix == "wri":
        return f"Writer {val}"
    if prefix == "cast":
        return val
    if prefix == "studio":
        return val
    if prefix == "col":
        return val
    if prefix == "genre":
        return val
    if prefix == "gpair":
        return val.replace("+", " · ")
    if prefix == "country":
        return f"{val} Cinema"
    if prefix == "decade":
        return val
    if prefix == "theme":
        return f"Theme: {val}"
    return val


def parse_natural_prompt(prompt: str) -> dict[str, Any]:
    """Extract lightweight structural constraints & search terms from a natural-language mood query."""
    q = (prompt or "").strip()
    if not q:
        return {"tokens": [], "raw_lower": "", "max_min": None, "media_hint": None, "decade_hint": None}

    low = q.lower()
    max_min: int | None = None
    m_min = re.search(r"(?:under|less than|<|max)\s*(\d{2,3})\s*(?:m|min|mins|minutes)", low)
    if m_min:
        max_min = int(m_min.group(1))
    elif "under 2 hours" in low or "under two hours" in low or "short movie" in low:
        max_min = 115
    elif "under 90" in low or "90 min" in low:
        max_min = 95

    media_hint: str | None = None
    if re.search(r"\b(tv|show|shows|series|miniseries|binge)\b", low) and not re.search(r"\b(movie|movies|film|films)\b", low):
        media_hint = "show"
    elif re.search(r"\b(movie|movies|film|films)\b", low) and not re.search(r"\b(tv|show|shows|series)\b", low):
        media_hint = "movie"

    decade_hint: str | None = None
    m_dec = re.search(r"\b(19[5-9]0|20[0-2]0)s?\b", low)
    if m_dec:
        decade_hint = f"{m_dec.group(1)}s"
    else:
        m_short_dec = re.search(r"\b([6-9]0)s\b", low)
        if m_short_dec:
            decade_hint = f"19{m_short_dec.group(1)}s"

    words = [w for w in re.findall(r"[a-z0-9]{3,20}", low) if w not in STOPWORDS and w not in {"movie", "movies", "film", "films", "show", "shows", "series", "something", "watch", "tonight", "like", "good", "great", "best"}]
    return {
        "tokens": words,
        "raw_lower": low,
        "max_min": max_min,
        "media_hint": media_hint,
        "decade_hint": decade_hint,
    }


class RecommendationEngine:
    """
    Fast IDF-weighted taste graph & anti-commercial recommendation engine.
    Runs across tens of thousands of local + shared Plex items in milliseconds.
    """

    def load_context(self) -> dict[str, Any]:
        with db_session() as conn:
            servers = {
                r["machine_id"]: dict(r)
                for r in conn.execute("SELECT * FROM servers").fetchall()
            }
            profiles = {
                r["id"]: dict(r)
                for r in conn.execute("SELECT * FROM profiles").fetchall()
            }
            media_rows = [
                dict(r) for r in conn.execute("SELECT * FROM media_items").fetchall()
            ]
            sources_by_media: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for s in conn.execute("SELECT * FROM media_sources").fetchall():
                sd = dict(s)
                srv = servers.get(sd["machine_id"])
                if not srv or not srv.get("enabled"):
                    continue
                sd["server_name"] = srv["name"]
                sd["owned"] = int(srv["owned"])
                sd["owner_name"] = srv["owner_name"]
                sd["online"] = int(srv["online"])
                sd["latency_ms"] = int(srv["latency_ms"])
                sd["deep_link"] = build_plex_deep_link(sd["machine_id"], sd["rating_key"])
                sources_by_media[int(sd["media_id"])].append(sd)

            feedback_by_profile: dict[str, dict[int, str]] = defaultdict(dict)
            for fb in conn.execute("SELECT profile_id, media_id, sentiment FROM taste_feedback").fetchall():
                feedback_by_profile[fb["profile_id"]][int(fb["media_id"])] = fb["sentiment"]

        # Precompute item features & IDF across corpus
        doc_freq: Counter[str] = Counter()
        item_features: dict[int, dict[str, float]] = {}
        for row in media_rows:
            feats = extract_item_features(row)
            item_features[int(row["id"])] = feats
            for f in feats:
                doc_freq[f] += 1

        n_docs = max(1, len(media_rows))
        idf: dict[str, float] = {
            f: math.log(1.0 + (n_docs / (1.0 + df)))
            for f, df in doc_freq.items()
        }

        return {
            "servers": servers,
            "profiles": profiles,
            "media_rows": media_rows,
            "sources_by_media": sources_by_media,
            "feedback_by_profile": feedback_by_profile,
            "item_features": item_features,
            "idf": idf,
            "doc_freq": doc_freq,
        }

    def build_profile_taste(
        self,
        ctx: dict[str, Any],
        profile_id: str = "together",
    ) -> dict[str, Any]:
        profile = ctx["profiles"].get(profile_id) or next(iter(ctx["profiles"].values()))
        inherit_shared = bool(profile.get("inherit_shared_history", 1))
        now_ts = int(time.time())
        idf = ctx["idf"]

        pos_vec: defaultdict[str, float] = defaultdict(float)
        neg_vec: defaultdict[str, float] = defaultdict(float)
        # Track top watched contributor titles per feature for transparent explanations
        feat_contributors: defaultdict[str, list[tuple[float, str]]] = defaultdict(list)

        positive_items: list[tuple[float, dict[str, Any], str]] = []
        negative_items: list[tuple[float, dict[str, Any], str]] = []

        for row in ctx["media_rows"]:
            w, reason = compute_item_signal_weight(
                row, profile_id, inherit_shared, ctx["feedback_by_profile"], now_ts
            )
            if abs(w) < 0.05:
                continue
            mid = int(row["id"])
            feats = ctx["item_features"].get(mid, {})
            if w > 0:
                positive_items.append((w, row, reason))
                for f, fw in feats.items():
                    contrib = w * fw * idf.get(f, 1.0)
                    pos_vec[f] += contrib
                    feat_contributors[f].append((w * fw, row["title"]))
            else:
                negative_items.append((w, row, reason))
                for f, fw in feats.items():
                    neg_vec[f] += abs(w) * fw * idf.get(f, 1.0)

        # Normalize vectors lightly so power-watchers and newer users have comparable scales
        pos_norm = math.sqrt(sum(v * v for v in pos_vec.values())) or 1.0
        neg_norm = math.sqrt(sum(v * v for v in neg_vec.values())) or 1.0

        for f in feat_contributors:
            feat_contributors[f].sort(key=lambda x: x[0], reverse=True)

        positive_items.sort(key=lambda x: (x[0], x[1].get("last_viewed_at") or 0), reverse=True)
        negative_items.sort(key=lambda x: x[0])

        # Summarize top DNA traits for UI & LLM context
        def top_prefix(prefix: str, k: int = 8) -> list[dict[str, Any]]:
            scored = [
                (f.split(":", 1)[1], val / pos_norm)
                for f, val in pos_vec.items()
                if f.startswith(f"{prefix}:") and val > 0
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [{"name": name, "weight": round(w, 3)} for name, w in scored[:k]]

        return {
            "profile": profile,
            "pos_vec": pos_vec,
            "neg_vec": neg_vec,
            "pos_norm": pos_norm,
            "neg_norm": neg_norm,
            "feat_contributors": feat_contributors,
            "positive_items": positive_items,
            "negative_items": negative_items,
            "dna": {
                "signal_count": len(positive_items) + len(negative_items),
                "loved_count": len(positive_items),
                "disliked_or_abandoned_count": len(negative_items),
                "top_directors": top_prefix("dir", 8),
                "top_writers": top_prefix("wri", 6),
                "top_genres": top_prefix("genre", 8),
                "top_pairings": [
                    {"name": x["name"].replace("+", " + "), "weight": x["weight"]}
                    for x in top_prefix("gpair", 6)
                ],
                "top_studios": top_prefix("studio", 6),
                "top_actors": top_prefix("cast", 8),
                "top_countries": [x for x in top_prefix("country", 5) if x["name"] != "US"],
                "top_decades": top_prefix("decade", 5),
                "top_themes": top_prefix("theme", 12),
                "anchor_favorites": [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "year": r.get("year"),
                        "media_type": r["media_type"],
                        "reason": reason,
                        "weight": round(w, 2),
                        "discover_rating_key": r.get("discover_rating_key"),
                    }
                    for w, r, reason in positive_items[:18]
                ],
                "avoid_examples": [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "year": r.get("year"),
                        "reason": reason,
                    }
                    for _, r, reason in negative_items[:10]
                ],
            },
        }

    def recommend(
        self,
        profile_id: str = "together",
        mood: str = "all",
        media_type: str = "all",
        source_scope: str = "plex_all",
        include_outside: bool = False,
        discovery_level: float = 0.35,
        max_duration: int | None = None,
        decade: str | None = None,
        prompt: str = "",
        exclude_watchlist: bool = False,
        limit: int = 36,
    ) -> dict[str, Any]:
        ctx = self.load_context()
        taste = self.build_profile_taste(ctx, profile_id=profile_id)
        parsed_prompt = parse_natural_prompt(prompt)

        effective_mtype = media_type
        if effective_mtype == "all" and parsed_prompt["media_hint"]:
            effective_mtype = parsed_prompt["media_hint"]

        effective_max_dur = max_duration or parsed_prompt["max_min"]
        effective_decade = decade or parsed_prompt["decade_hint"]

        mood_cfg = MOOD_DEFINITIONS.get(mood)
        effective_discovery = (
            max(discovery_level, mood_cfg["force_discovery"])
            if mood_cfg and "force_discovery" in mood_cfg
            else discovery_level
        )

        pos_vec = taste["pos_vec"]
        neg_vec = taste["neg_vec"]
        pos_norm = taste["pos_norm"]
        neg_norm = taste["neg_norm"]
        idf = ctx["idf"]
        has_taste_history = len(taste["positive_items"]) > 0
        prof_feedback = ctx["feedback_by_profile"].get(profile_id, {})

        scored_candidates: list[dict[str, Any]] = []

        for row in ctx["media_rows"]:
            mid = int(row["id"])
            fb = prof_feedback.get(mid)

            # Never recommend already watched items or explicitly rated/dismissed items
            if row.get("is_watched") or fb in ("love", "like", "meh", "dislike", "dismiss", "seen_unrated"):
                continue
            if exclude_watchlist and row.get("on_watchlist"):
                continue

            mtype = row["media_type"]
            if effective_mtype in ("movie", "show") and mtype != effective_mtype:
                continue

            sources = ctx["sources_by_media"].get(mid, [])
            is_ext = len(sources) == 0

            # Filter by availability scope
            if is_ext and not include_outside:
                continue
            if not is_ext:
                if source_scope == "local_only" and not any(s["owned"] == 1 for s in sources):
                    continue
                if source_scope == "shared_only" and not any(s["owned"] == 0 for s in sources):
                    continue
            elif source_scope in ("local_only", "shared_only") and not include_outside:
                continue

            dur = row.get("duration_min")
            if effective_max_dur and mtype == "movie" and dur and dur > effective_max_dur:
                continue
            if mood_cfg:
                if mtype == "movie" and "max_movie_min" in mood_cfg and dur and dur > mood_cfg["max_movie_min"]:
                    continue
                if mtype == "show" and "max_show_min" in mood_cfg and dur and dur > mood_cfg["max_show_min"]:
                    continue
                if mtype == "movie" and "min_movie_min" in mood_cfg and dur and dur < mood_cfg["min_movie_min"]:
                    continue

            yr = row.get("year")
            if effective_decade:
                if not yr or f"{(int(yr) // 10) * 10}s" != effective_decade:
                    continue

            feats = ctx["item_features"].get(mid, {})
            item_norm = math.sqrt(sum((fw * idf.get(f, 1.0)) ** 2 for f, fw in feats.items())) or 1.0

            # 1. Personal Taste Graph Affinity
            feature_hits: list[tuple[float, str]] = []
            pos_dot = 0.0
            neg_dot = 0.0
            for f, fw in feats.items():
                w_idf = fw * idf.get(f, 1.0)
                pv = pos_vec.get(f, 0.0)
                if pv > 0:
                    c = pv * w_idf
                    pos_dot += c
                    if not f.startswith("country:US"):
                        feature_hits.append((c, f))
                nv = neg_vec.get(f, 0.0)
                if nv > 0:
                    neg_dot += nv * w_idf

            taste_sim = (pos_dot / (pos_norm * item_norm)) if has_taste_history else 0.25
            neg_sim = (neg_dot / (neg_norm * item_norm)) if taste["negative_items"] else 0.0
            net_taste = taste_sim - (0.58 * neg_sim)

            # 2. Non-commercial quality signal (audience + critic Bayesian prior)
            quality = compute_quality_prior(row.get("critic_rating"), row.get("audience_rating"))
            if mood_cfg and "min_quality" in mood_cfg:
                raw_best_r = max(float(row.get("audience_rating") or 0), float(row.get("critic_rating") or 0))
                if raw_best_r > 0 and raw_best_r < mood_cfg["min_quality"]:
                    continue

            # 3. Discovery / Hidden-Gem bonus (rewards high quality + non-ubiquitous / international / indie / classic gems)
            server_ubiquity = min(1.0, max(0, len(sources) - 1) / 3.0)
            genres_set = set(json_loads_list(row.get("genres_json")))
            countries_list = json_loads_list(row.get("countries_json"))
            is_intl = any(c not in ("United States of America", "USA", "US") for c in countries_list)
            is_older_gem = bool(yr and int(yr) <= 2012 and quality >= 0.68)
            gem_factor = (
                (1.0 - 0.55 * server_ubiquity) * quality
                + (0.14 if is_intl else 0.0)
                + (0.12 if is_older_gem else 0.0)
            )

            # 4. Mood alignment
            mood_delta = 0.0
            if mood_cfg:
                overlap_boost = len(genres_set & mood_cfg["boost_genres"])
                overlap_pen = len(genres_set & mood_cfg["penalize_genres"])
                if mood_cfg["boost_genres"] and overlap_boost == 0:
                    mood_delta -= 0.14
                else:
                    mood_delta += min(0.28, overlap_boost * 0.14)
                mood_delta -= overlap_pen * 0.28

                if mood_cfg["keywords"]:
                    summary_low = f"{row.get('tagline') or ''} {row.get('summary') or ''}".lower()
                    kw_hits = sum(1 for kw in mood_cfg["keywords"] if kw in summary_low)
                    mood_delta += min(0.24, kw_hits * 0.08)

            # 5. Free-text prompt matching (works locally even without LLM!)
            prompt_boost = 0.0
            if parsed_prompt["tokens"]:
                haystack = (
                    f"{row['title']} {row.get('original_title') or ''} {row.get('tagline') or ''} "
                    f"{row.get('summary') or ''} {' '.join(genres_set)} "
                    f"{' '.join(json_loads_list(row.get('directors_json')))} "
                    f"{' '.join(json_loads_list(row.get('writers_json')))} "
                    f"{' '.join(json_loads_list(row.get('cast_json')))} "
                    f"{' '.join(json_loads_list(row.get('countries_json')))} "
                    f"{' '.join(json_loads_list(row.get('studios_json')))}"
                ).lower()
                matched_toks = sum(1 for t in parsed_prompt["tokens"] if t in haystack)
                if matched_toks == 0:
                    prompt_boost -= 0.22
                else:
                    prompt_boost += 0.22 * (matched_toks / len(parsed_prompt["tokens"])) + 0.08 * matched_toks

            total_score = (
                (net_taste * 2.35)
                + (quality * (0.55 - 0.15 * effective_discovery))
                + (gem_factor * (0.45 * effective_discovery))
                + mood_delta
                + prompt_boost
            )

            # Build transparent human explanation ("Because you loved X & Y" + top matching facets)
            feature_hits.sort(key=lambda x: x[0], reverse=True)
            top_reasons: list[str] = []
            seen_reason_labels: set[str] = set()
            contributor_titles: Counter[str] = Counter()

            for c_val, f_key in feature_hits[:8]:
                lbl = human_feature_label(f_key)
                if lbl not in seen_reason_labels and len(top_reasons) < 4:
                    seen_reason_labels.add(lbl)
                    top_reasons.append(lbl)
                for w_c, c_title in taste["feat_contributors"].get(f_key, [])[:3]:
                    if c_title != row["title"]:
                        contributor_titles[c_title] += c_val * w_c

            because_titles = [t for t, _ in contributor_titles.most_common(3)]
            best_rating = row.get("audience_rating") or row.get("critic_rating")
            if best_rating and float(best_rating) >= 8.0 and len(top_reasons) < 4:
                top_reasons.append(f"Acclaimed ({float(best_rating):.1f}/10)")

            scored_candidates.append(
                {
                    "row": row,
                    "sources": sources,
                    "raw_score": total_score,
                    "feats": feats,
                    "because_titles": because_titles,
                    "match_reasons": top_reasons,
                }
            )

        scored_candidates.sort(key=lambda x: x["raw_score"], reverse=True)

        # Diversify top candidates via Maximal Marginal Relevance (MMR)
        shortlist = scored_candidates[: min(180, len(scored_candidates))]
        selected = self._diversify_mmr(shortlist, limit=limit, lambda_param=0.78)

        # Map scores cleanly onto an intuitive 64..99% match scale relative to top candidate
        top_s = selected[0]["raw_score"] if selected else 1.0
        bot_s = selected[-1]["raw_score"] if len(selected) > 1 else (top_s - 0.5)
        span = max(0.25, top_s - bot_s)

        results: list[dict[str, Any]] = []
        for idx, entry in enumerate(selected):
            row = entry["row"]
            hydrated = hydrate_media_row(row, sources=entry["sources"], feedback_sentiment=None)
            rel = (entry["raw_score"] - bot_s) / span
            match_pct = int(round(max(62.0, min(98.0, 72.0 + 26.0 * rel - idx * 0.12))))
            because = entry["because_titles"]
            reasons = entry["match_reasons"]

            if because:
                if len(because) == 1:
                    pitch = f"Picked because you liked {because[0]}"
                else:
                    pitch = f"Connects to {', '.join(because[:-1])} & {because[-1]}"
                if reasons:
                    pitch += f" ({', '.join(reasons[:2])})."
                else:
                    pitch += "."
            elif reasons:
                pitch = f"Strong match on {', '.join(reasons[:3])}."
            else:
                pitch = "High-acclaim pick aligned with your filters."

            hydrated["match_score"] = match_pct
            hydrated["because_you_liked"] = because
            hydrated["match_reasons"] = reasons
            hydrated["explanation"] = pitch
            hydrated["ai_curated"] = False
            results.append(hydrated)

        return {
            "items": results,
            "dna": taste["dna"],
            "total_pool": len(scored_candidates),
            "profile": taste["profile"],
        }

    def _diversify_mmr(
        self,
        candidates: list[dict[str, Any]],
        limit: int,
        lambda_param: float = 0.78,
    ) -> list[dict[str, Any]]:
        if len(candidates) <= limit:
            return candidates

        # Normalize raw_score into [0, 1] across candidate pool for stable MMR trade-off
        hi = candidates[0]["raw_score"]
        lo = candidates[-1]["raw_score"]
        denom = max(1e-6, hi - lo)

        chosen: list[dict[str, Any]] = []
        remaining = list(candidates)

        while remaining and len(chosen) < limit:
            if not chosen:
                chosen.append(remaining.pop(0))
                continue

            best_idx = 0
            best_mmr = -1e9
            for i, cand in enumerate(remaining):
                rel = (cand["raw_score"] - lo) / denom
                c_feats = set(cand["feats"].keys())
                # Penalize duplicate directors, collections, or very high feature overlap
                max_sim = 0.0
                for prev in chosen[-12:]:
                    p_feats = set(prev["feats"].keys())
                    if not c_feats or not p_feats:
                        continue
                    inter = c_feats & p_feats
                    sim = len(inter) / math.sqrt(len(c_feats) * len(p_feats))
                    if any(k.startswith("dir:") or k.startswith("col:") for k in inter):
                        sim += 0.35
                    if sim > max_sim:
                        max_sim = sim
                mmr_val = lambda_param * rel - (1.0 - lambda_param) * max_sim
                if mmr_val > best_mmr:
                    best_mmr = mmr_val
                    best_idx = i

            chosen.append(remaining.pop(best_idx))

        return chosen

    def get_watch_history(
        self,
        profile_id: str = "together",
        filter_mode: str = "all",
        media_type: str = "all",
        search: str = "",
        limit: int = 120,
    ) -> dict[str, Any]:
        ctx = self.load_context()
        taste = self.build_profile_taste(ctx, profile_id=profile_id)
        prof_fb = ctx["feedback_by_profile"].get(profile_id, {})
        inherit_shared = bool(taste["profile"].get("inherit_shared_history", 1))
        now_ts = int(time.time())
        q_low = search.strip().lower()

        items: list[dict[str, Any]] = []
        counts = {"all": 0, "unrated": 0, "loved": 0, "disliked": 0, "abandoned": 0}

        for row in ctx["media_rows"]:
            mid = int(row["id"])
            fb = prof_fb.get(mid)
            is_relevant = bool(row.get("is_watched")) or (fb is not None)
            if not is_relevant:
                continue
            if media_type in ("movie", "show") and row["media_type"] != media_type:
                continue
            if q_low and q_low not in row["title"].lower():
                continue

            counts["all"] += 1
            if not fb:
                counts["unrated"] += 1
            if fb in ("love", "like"):
                counts["loved"] += 1
            if fb in ("dislike", "meh"):
                counts["disliked"] += 1
            if row.get("is_abandoned"):
                counts["abandoned"] += 1

            if filter_mode == "unrated" and fb is not None:
                continue
            if filter_mode == "loved" and fb not in ("love", "like"):
                continue
            if filter_mode == "disliked" and fb not in ("dislike", "meh"):
                continue
            if filter_mode == "abandoned" and not row.get("is_abandoned"):
                continue

            sig_w, sig_reason = compute_item_signal_weight(
                row, profile_id, inherit_shared, ctx["feedback_by_profile"], now_ts
            )
            hydrated = hydrate_media_row(
                row,
                sources=ctx["sources_by_media"].get(mid, []),
                feedback_sentiment=fb,
            )
            hydrated["implicit_signal"] = sig_reason
            hydrated["signal_weight"] = round(sig_w, 2)
            items.append(hydrated)

        items.sort(
            key=lambda x: (
                x.get("last_viewed_at") or 0,
                abs(x.get("signal_weight") or 0),
                x.get("year") or 0,
            ),
            reverse=True,
        )
        return {
            "items": items[:limit],
            "total_matching": len(items),
            "counts": counts,
            "dna": taste["dna"],
        }


ENGINE = RecommendationEngine()
