import argparse
from urllib.parse import urlunsplit

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lumen API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    display_host = (
        f"[{args.host}]" if ":" in args.host and not args.host.startswith("[") else args.host
    )
    health_url = urlunsplit(("http", f"{display_host}:{args.port}", "/health/live", "", ""))
    print(f"Health check: {health_url}", flush=True)
    uvicorn.run("lumen.main:app", host=args.host, port=args.port, reload=args.reload)
