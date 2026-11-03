from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.db as db_mod
import backend.main as main_mod
import backend.recommender as rec_mod
from backend.plex_client import extract_canonical_identity


@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    test_db_path = tmp_path / "test_plexbot.db"
    monkeypatch.setattr(db_mod, "DB_PATH", test_db_path)
    db_mod.init_db(test_db_path)
    return test_db_path


def _seed_sample_catalog(db_path: Path) -> None:
    now = int(time.time())
    old_ts = now - 60 * 86400
    db_mod.set_settings_bulk(
        {"plex_token": "test-token", "plex_username": "peter"},
        db_path=db_path,
    )

    with db_mod.db_session(db_path) as conn:
        # 1 local server + 1 friend's shared server
        conn.execute(
            """
            INSERT INTO servers (machine_id, name, owned, owner_name, base_url, access_token, online, enabled, movie_count, show_count)
            VALUES
              ('srv-local', 'Mac Local Plex', 1, 'You (Local)', 'http://127.0.0.1:32400', 'tok1', 1, 1, 3, 1),
              ('srv-friend', 'Dave Shared NAS', 0, 'dave', 'https://dave.plex.direct:32400', 'tok2', 1, 1, 4, 1)
            """
        )

        items = [
            # 1. Watched & Rewatched Denis Villeneuve Sci-Fi (strong positive)
            (
                "plex:movie:rk_arrival",
                "movie",
                "plex://movie/rk_arrival",
                "rk_arrival",
                "Arrival",
                2016,
                116,
                9.4,
                8.2,
                ["Science Fiction", "Drama", "Mystery"],
                ["Denis Villeneuve"],
                ["Eric Heisserer"],
                ["Amy Adams", "Jeremy Renner"],
                "A linguist investigates alien spacecraft and time perception.",
                1,
                2,
                None,
                0,
                now - 86400 * 10,
                0,
                "srv-local",
                "101",
                "4K",
            ),
            # 2. Watched Villeneuve Thriller (positive)
            (
                "plex:movie:rk_sicario",
                "movie",
                "plex://movie/rk_sicario",
                "rk_sicario",
                "Sicario",
                2015,
                121,
                9.2,
                8.0,
                ["Thriller", "Crime", "Drama"],
                ["Denis Villeneuve"],
                ["Taylor Sheridan"],
                ["Emily Blunt", "Benicio del Toro"],
                "An idealistic FBI agent joins a covert cartel task force on the border.",
                1,
                1,
                9.0,
                0,
                now - 86400 * 20,
                0,
                "srv-local",
                "102",
                "1080p",
            ),
            # 3. Abandoned slapstick horror movie (negative implicit signal!)
            (
                "plex:movie:rk_zombielow",
                "movie",
                "plex://movie/rk_zombielow",
                "rk_zombielow",
                "Zombie Clowns 4",
                2022,
                98,
                3.1,
                3.5,
                ["Horror"],
                ["Alan Smithee"],
                ["Alan Smithee"],
                ["Actor One"],
                " Grisly clowns attack a carnival.",
                1,
                0,
                None,
                1,
                old_ts,
                0,
                "srv-friend",
                "201",
                "1080p",
            ),
            # 4. Unwatched Candidate A on Friend's Shared Server: Prisoners (Villeneuve Thriller - should rank #1!)
            (
                "plex:movie:rk_prisoners",
                "movie",
                "plex://movie/rk_prisoners",
                "rk_prisoners",
                "Prisoners",
                2013,
                153,
                8.1,
                8.2,
                ["Thriller", "Crime", "Mystery", "Drama"],
                ["Denis Villeneuve"],
                ["Aaron Guzikowski"],
                ["Hugh Jackman", "Jake Gyllenhaal"],
                "A detective and desperate father investigate a mysterious disappearance.",
                0,
                0,
                None,
                0,
                None,
                0,
                "srv-friend",
                "202",
                "4K",
            ),
            # 5. Unwatched Candidate B on Local Server: Tight 95m Sci-Fi Mystery (great for weeknight!)
            (
                "plex:movie:rk_coherence",
                "movie",
                "plex://movie/rk_coherence",
                "rk_coherence",
                "Coherence",
                2013,
                89,
                8.8,
                7.6,
                ["Science Fiction", "Mystery", "Thriller"],
                ["James Ward Byrkit"],
                ["James Ward Byrkit"],
                ["Emily Baldoni"],
                "Strange quantum reality anomalies fracture a dinner party when a comet passes.",
                0,
                0,
                None,
                0,
                None,
                0,
                "srv-local",
                "103",
                "1080p",
            ),
            # 6. Unwatched Candidate C on Friend's Server: Cheap Slasher Horror (should rank bottom due to abandoned horror + low quality)
            (
                "plex:movie:rk_clown5",
                "movie",
                "plex://movie/rk_clown5",
                "rk_clown5",
                "Zombie Clowns 5",
                2023,
                92,
                2.8,
                3.2,
                ["Horror"],
                ["Alan Smithee"],
                ["Alan Smithee"],
                ["Actor One"],
                "More carnival clowns.",
                0,
                0,
                None,
                0,
                None,
                0,
                "srv-friend",
                "203",
                "720p",
            ),
            # 7. Outside Plex Discovery item
            (
                "plex:movie:rk_incendies",
                "movie",
                "plex://movie/rk_incendies",
                "rk_incendies",
                "Incendies",
                2010,
                131,
                9.1,
                8.4,
                ["Drama", "Mystery"],
                ["Denis Villeneuve"],
                ["Denis Villeneuve"],
                ["Lubna Azabal"],
                "Twins journey to the Middle East to uncover their mother's hidden past.",
                0,
                0,
                None,
                0,
                None,
                1,
                None,
                None,
                "",
            ),
        ]

        for (
            ckey, mtype, pguid, drk, title, yr, dur, cr, ar,
            genres, dirs, wris, cast, summary,
            watched, vc, ur, aband, lv, ext_only, srv_id, rk, res
        ) in items:
            cur = conn.execute(
                """
                INSERT INTO media_items (
                    canonical_key, media_type, plex_guid, discover_rating_key, title, year,
                    duration_min, critic_rating, audience_rating, genres_json, directors_json,
                    writers_json, cast_json, summary, is_watched, max_view_count, max_user_rating,
                    is_abandoned, last_viewed_at, is_external_only
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ckey, mtype, pguid, drk, title, yr,
                    dur, cr, ar, json.dumps(genres), json.dumps(dirs),
                    json.dumps(wris), json.dumps(cast), summary,
                    watched, vc, ur, aband, lv, ext_only,
                ),
            )
            mid = int(cur.lastrowid)
            if srv_id and rk:
                conn.execute(
                    """
                    INSERT INTO media_sources (
                        media_id, machine_id, rating_key, section_id, section_title,
                        resolution, view_count, user_rating, last_viewed_at
                    ) VALUES (?, ?, ?, '1', 'Movies', ?, ?, ?, ?)
                    """,
                    (mid, srv_id, rk, res, vc, ur, lv),
                )


def test_canonical_deduplication_identity():
    item_plex = {
        "guid": "plex://movie/5d7768248a7581001f12bc06",
        "title": "Blade Runner 2049",
        "year": 2017,
        "Guid": [{"id": "imdb://tt1856101"}, {"id": "tmdb://335984"}],
    }
    ckey, pguid, drk, imdb, tmdb = extract_canonical_identity(item_plex, "movie")
    assert ckey == "plex:movie:5d7768248a7581001f12bc06"
    assert drk == "5d7768248a7581001f12bc06"
    assert imdb == "tt1856101"
    assert tmdb == "335984"

    item_legacy = {
        "guid": "com.plexapp.agents.imdb://tt1856101?lang=en",
        "title": "Blade Runner 2049",
        "year": 2017,
    }
    ckey2, _, drk2, imdb2, _ = extract_canonical_identity(item_legacy, "movie")
    assert ckey2 == "imdb:movie:tt1856101"
    assert drk2 is None
    assert imdb2 == "tt1856101"


def test_taste_graph_ranking_and_scopes(temp_db: Path):
    _seed_sample_catalog(temp_db)
    engine = rec_mod.RecommendationEngine()

    # 1. Default recommendations: playable across local + shared servers only (excludes outside Incendies)
    res = engine.recommend(profile_id="together", include_outside=False)
    titles = [it["title"] for it in res["items"]]
    assert "Arrival" not in titles  # Already watched
    assert "Zombie Clowns 4" not in titles  # Abandoned
    assert "Incendies" not in titles  # Outside Plex disabled by default
    assert titles[0] == "Prisoners"  # Matches Denis Villeneuve + Thriller/Mystery/Drama
    assert titles[-1] == "Zombie Clowns 5"  # Penalized by abandoned Zombie Clowns 4 + low quality
    assert "Arrival" in res["items"][0]["explanation"] or "Sicario" in res["items"][0]["explanation"]

    # 2. Local server only filter
    local_res = engine.recommend(profile_id="together", source_scope="local_only")
    assert [it["title"] for it in local_res["items"]] == ["Coherence"]

    # 3. Weeknight (<108m) mood filters out 153-minute Prisoners and highlights 89-minute Coherence
    weeknight_res = engine.recommend(profile_id="together", mood="weeknight")
    wn_titles = [it["title"] for it in weeknight_res["items"]]
    assert "Prisoners" not in wn_titles
    assert wn_titles[0] == "Coherence"

    # 4. Outside discoveries toggle surfaces Incendies
    out_res = engine.recommend(profile_id="together", include_outside=True)
    out_titles = [it["title"] for it in out_res["items"]]
    assert "Incendies" in out_titles


def test_household_profile_blending_and_api(temp_db: Path):
    _seed_sample_catalog(temp_db)
    client = TestClient(main_mod.app)

    status = client.get("/api/status").json()
    assert status["authenticated"] is True
    assert status["stats"]["total_movies"] == 6
    assert len(status["servers"]) == 2

    # Search Prisoners and mark 'dislike' on 'partner' profile -> verify 'together' demotes it,
    # while 'me' still gets Prisoners #1!
    search_res = client.get("/api/catalog/search?q=Arrival&profile_id=partner").json()
    arrival_id = search_res["items"][0]["id"]

    # Partner dislikes Arrival & Sicario
    sicario_id = client.get("/api/catalog/search?q=Sicario&profile_id=partner").json()["items"][0]["id"]
    client.post(
        "/api/feedback",
        json={"profile_id": "partner", "media_id": arrival_id, "sentiment": "dislike"},
    )
    client.post(
        "/api/feedback",
        json={"profile_id": "partner", "media_id": sicario_id, "sentiment": "dislike"},
    )

    me_recs = client.get("/api/recommendations?profile_id=me").json()["items"]
    assert me_recs[0]["title"] == "Prisoners"

    partner_recs = client.get("/api/recommendations?profile_id=partner").json()["items"]
    # Partner disliked Villeneuve films, so Coherence outranks Prisoners for partner
    assert partner_recs[0]["title"] == "Coherence"

    hist = client.get("/api/history?profile_id=partner&filter_mode=disliked").json()
    assert hist["counts"]["disliked"] == 2
