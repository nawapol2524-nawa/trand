"""
Dashboard Launcher Script.
Run with: python -m webboard.run_dashboard --port 8080
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from webboard.server import run_server


def main():
    parser = argparse.ArgumentParser(description="Unified Trading Bot Webboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()

    run_server(port=args.port, host=args.host, workspace_root=str(root_dir))


if __name__ == "__main__":
    main()
