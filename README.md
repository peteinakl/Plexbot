# Plexbot

A personal, zero-commercial-bias movie & TV recommender built specifically for **Plex** — unifying both your **local Plex Media Server** and **friends' shared Plex libraries** into a single taste-driven screening room.

## Why It Beats Netflix's Algorithm

1. **Unified Local + Shared Libraries**: Connects via standard Plex OAuth PIN sign-in to discover your local Mac server *and* every friend's shared Plex server, deduplicating titles across servers and showing where each pick is playable (4K / 1080p / HDR) with direct **Open in Plex** deep links.
2. **Real Implicit + Explicit Taste Signals**: Evaluates completed watches, rewatches, episode completion ratios, Plex star ratings, and **abandoned** movies/shows (things you turned off 20 minutes in), weighted across an Inverse-Document-Frequency (IDF) graph of directors, writers, cast, studios, genre pairings, eras, and plot themes.
3. **Built for Shared Plex Accounts**: Includes **Who's Watching** modes (*Us Together*, *Just Me*, *Partner / Family*, plus custom profiles) and rapid 1-click thumbs calibration so someone else's binge doesn't skew your solo recommendations — while *Us Together* automatically vetoes anything either person disliked.
4. **Hybrid AI Brain**: Scores tens of thousands of titles locally in milliseconds with zero API keys, and optionally pairs with **Google Gemini**, **Anthropic Claude**, or **OpenAI** for natural-language mood curation, bespoke explanations, outside-Plex discoveries, and an **AI Taste Portrait**.
5. **1-Click Universal Plex Watchlist**: Add any local, shared, or outside discovery straight to your Plex Watchlist so it immediately appears on your TV, Apple TV, or Plex mobile app.
6. **Netflix Catalog & Viewing History CSV Integration**: Indexes regional Netflix titles alongside your Plex servers (zero extra API keys needed via Plex Discover, plus optional TMDB expansion) with direct **Watch on Netflix** title links, and imports `NetflixViewingActivity.csv` to roll episodes up into shows, detect abandoned series, and enrich your taste graph.

## Quick Start

```bash
./start.sh
```

This starts Plexbot locally at **http://127.0.0.1:8765** and opens it in your browser.

To run manually without opening a browser tab:

```bash
.venv/bin/python run.py
```

## Optional Cloud LLM Keys

You can paste an API key directly inside Plexbot's **Settings** modal (stored locally in `data/plexbot.db` with `0600` owner-only permissions), or export `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` before launching.
