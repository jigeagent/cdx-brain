"""CLI entry for `python -m cdx_brain.viewer`."""

from __future__ import annotations

import argparse
import os
import sys

from cdx_brain.viewer.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes Next Viewer")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CDX_VIEWER_PORT", "8080")))
    parser.add_argument("--host", default=os.environ.get("CDX_VIEWER_HOST", "127.0.0.1"))
    parser.add_argument("--db", dest="cache_path", default=os.environ.get("CDX_CACHE_DB", "~/.hermes-next/cache.db"))
    parser.add_argument("--ov-url", default=os.environ.get("OV_URL", "http://localhost:1933"))
    args = parser.parse_args()
    serve(cache_path=args.cache_path, ov_url=args.ov_url, port=args.port, host=args.host)


if __name__ == "__main__":
    main()
