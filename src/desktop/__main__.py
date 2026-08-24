from __future__ import annotations

import argparse
import os
import sys

from .server import DEFAULT_HOST, DEFAULT_PORT, run_desktop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jonathan Ai desktop host")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (localhost only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLAWD_DESKTOP_PORT") or DEFAULT_PORT))
    parser.add_argument("--workspace", default=None, help="Initial workspace directory")
    parser.add_argument("--token", default=os.environ.get("CLAWD_DESKTOP_TOKEN"), help="API token for the UI")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    args = parser.parse_args(argv)
    return run_desktop(
        host=args.host,
        port=args.port,
        workspace=args.workspace,
        open_browser=not args.no_browser,
        token=args.token,
    )


if __name__ == "__main__":
    sys.exit(main())
