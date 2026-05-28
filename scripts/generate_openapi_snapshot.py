#!/usr/bin/env python3
"""Generate a deterministic OpenAPI snapshot from the Flask app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OpenAPI snapshot JSON")
    parser.add_argument(
        "--output",
        default="docs/openapi.json",
        help="Output file path (default: docs/openapi.json)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    bot_dir = repo_root / "bot"
    sys.path.insert(0, str(bot_dir))

    # Import after path setup.
    import app as bot_app  # type: ignore

    client = bot_app.app.test_client()
    response = client.get("/openapi.json")
    if response.status_code != 200:
        raise RuntimeError(f"failed to fetch /openapi.json from app test client: {response.status_code}")
    spec = response.get_json()
    if not isinstance(spec, dict):
        raise RuntimeError("invalid OpenAPI payload type; expected JSON object")

    output_path = repo_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote_openapi_snapshot={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
