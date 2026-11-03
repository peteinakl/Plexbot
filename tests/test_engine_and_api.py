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
    assert len(status["servers"]) == 3  # 2 Plex servers + Netflix source

    # Search Arrival and mark 'dislike' on 'partner' profile
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


def test_netflix_source_scoping_and_csv_import(temp_db: Path):
    _seed_sample_catalog(temp_db)
    # Add a Netflix-only title (Roma) into the DB
    with db_mod.db_session(temp_db) as conn:
        cur = conn.execute(
            """
            INSERT INTO media_items (
                canonical_key, media_type, plex_guid, discover_rating_key, title, year,
                duration_min, critic_rating, audience_rating, genres_json, directors_json,
                summary, is_watched, is_external_only
            ) VALUES (
                'plex:movie:rk_roma', 'movie', 'plex://movie/rk_roma', 'rk_roma', 'Roma', 2018,
                135, 9.6, 8.1, '["Drama"]', '["Alfonso Cuarón"]',
                'A vivid portrait of domestic life in 1970s Mexico City.', 0, 0
            )
            """
        )
        roma_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO media_sources (
                media_id, machine_id, rating_key, section_id, section_title, resolution
            ) VALUES (?, 'provider:netflix', 'nf:rk_roma', 'netflix', 'Netflix (NZ)', 'HD')
            """,
            (roma_id,),
        )

    client = TestClient(main_mod.app)

    # 1. Netflix-only scope returns only Roma with streaming source_type
    nf_only = client.get("/api/recommendations?source_scope=netflix_only").json()["items"]
    assert [it["title"] for it in nf_only] == ["Roma"]
    assert nf_only[0]["primary_source"]["source_type"] == "streaming"

    # 2. Plex-only scope excludes Netflix-only Roma
    plex_only = client.get("/api/recommendations?source_scope=plex_all").json()["items"]
    assert "Roma" not in [it["title"] for it in plex_only]

    # 3. All playable includes both Prisoners (Plex) and Roma (Netflix)
    all_play = client.get("/api/recommendations?source_scope=all_playable").json()["items"]
    all_titles = [it["title"] for it in all_play]
    assert "Prisoners" in all_titles and "Roma" in all_titles

    # 4. Import NetflixViewingActivity.csv marking Prisoners & Roma watched + rolling up a show
    # Clear plex_token temporarily so unit test doesn't make live external HTTP calls for unmatched shows
    db_mod.set_setting("plex_token", "", db_path=temp_db)
    csv_payload = (
        '\ufeffTitle,Date\n'
        '"Prisoners","14/09/25"\n'
        '"Roma","10/08/25"\n'
        '"Dark: Season 1: Secrets","01/07/25"\n'
        '"Dark: Season 1: Lies","02/07/25"\n'
        '"Dark: Season 1: Past and Present","03/07/25"\n'
    )
    imp = client.post("/api/netflix/import-csv", json={"csv_text": csv_payload}).json()
    assert imp["rows_parsed"] == 5
    assert imp["unique_titles"] == 3  # Prisoners, Roma, and rolled-up Dark!
    assert imp["movies_marked"] == 2

    # Restore token & verify Prisoners and Roma are no longer recommended as unwatched!
    db_mod.set_setting("plex_token", "test-token", db_path=temp_db)
    after_recs = client.get("/api/recommendations?source_scope=all_playable").json()["items"]
    after_titles = [it["title"] for it in after_recs]
    assert "Prisoners" not in after_titles
    assert "Roma" not in after_titles


def test_shared_server_privacy_redaction_and_redirect(temp_db: Path):
    _seed_sample_catalog(temp_db)
    # Add a second friend's shared Plex server also hosting Prisoners with a custom section title
    with db_mod.db_session(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO servers (machine_id, name, owned, owner_name, base_url, access_token, online, enabled, movie_count, show_count)
            VALUES ('srv-friend-2', 'Sarah Secret Vault', 0, 'sarah_nz', 'https://sarah.plex.direct:32400', 'tok3', 1, 1, 1, 0)
            """
        )
        prisoners_id = int(
            conn.execute("SELECT id FROM media_items WHERE title = 'Prisoners'").fetchone()["id"]
        )
        conn.execute(
            """
            INSERT INTO media_sources (
                media_id, machine_id, rating_key, section_id, section_title, resolution
            ) VALUES (?, 'srv-friend-2', '999', '4', 'Sarah Private Movies', '1080p')
            """,
            (prisoners_id,),
        )

    client = TestClient(main_mod.app)

    # 1. Recommendations, search, and history must NEVER expose friend server names, owners, custom sections, or machine IDs
    recs_resp = client.get("/api/recommendations?source_scope=all_playable")
    search_resp = client.get("/api/catalog/search?q=Prisoners")
    hist_resp = client.get("/api/history")

    for resp in (recs_resp, search_resp, hist_resp):
        assert resp.status_code == 200
        raw_json = resp.text
        for secret in (
            "Dave Shared NAS",
            "dave",
            "srv-friend",
            "Sarah Secret Vault",
            "sarah_nz",
            "srv-friend-2",
            "Sarah Private Movies",
        ):
            assert secret not in raw_json

    # 2. Owned local server name IS preserved on local items
    recs_items = recs_resp.json()["items"]
    coherence = next(it for it in recs_items if it["title"] == "Coherence")
    assert coherence["primary_source"]["server_name"] == "Mac Local Plex"
    assert coherence["primary_source"]["owned"] == 1

    # 3. Multi-shared item gets numbered generic labels ("Shared Plex #1", "Shared Plex #2") & opaque redirect links
    prisoners = next(it for it in recs_items if it["title"] == "Prisoners")
    assert [s["server_name"] for s in prisoners["sources"]] == ["Shared Plex #1", "Shared Plex #2"]
    assert all(s["machine_id"] == "shared" for s in prisoners["sources"])
    assert all(s["owner_name"] == "" for s in prisoners["sources"])
    assert all(s["section_title"] == "Shared Library" for s in prisoners["sources"])
    assert prisoners["primary_source"]["deep_link"].startswith("/api/plex/open/")

    # 4. Clicking /api/plex/open/{source_id} 302-redirects cleanly to app.plex.tv
    open_resp = client.get(prisoners["primary_source"]["deep_link"], follow_redirects=False)
    assert open_resp.status_code == 302
    assert open_resp.headers["location"].startswith(
        "https://app.plex.tv/desktop#!/server/srv-friend/details?key="
    )

    # 5. Settings endpoint (/api/status -> servers) still retains real names so SettingsModal can manage them
    status_servers = client.get("/api/status").json()["servers"]
    server_names = {s["name"] for s in status_servers}
    assert "Dave Shared NAS" in server_names
    assert "Sarah Secret Vault" in server_names
