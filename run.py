#!/usr/bin/env python3
from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import uvicorn

from backend.config import DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Plexbot local web server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port (default: 8765)")
    parser.add_argument("--open", action="store_true", help="Open Plexbot in your default browser")
    parser.add_argument("--reload", action="store_true", help="Auto-reload backend on code changes")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"\n🎬 Plexbot starting at {url}\n")

    if args.open:
        def _open_browser() -> None:
            time.sleep(1.1)
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
