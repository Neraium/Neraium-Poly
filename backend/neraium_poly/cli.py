"""Local commands are paper-only; collect reads public data."""

import argparse
import json
from pathlib import Path

from neraium_poly.settings import Settings


def main():
    parser = argparse.ArgumentParser(description="Neraium-Poly paper research")
    parser.add_argument("command", choices=["serve", "scenario", "collect"])
    parser.add_argument("--port", type=int, default=18740)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--cycles", type=int, default=1, help="Collection rounds; 0 runs until interrupted")
    parser.add_argument("--interval", type=float, default=30, help="Collection interval seconds, minimum 5")
    args = parser.parse_args()
    Settings.from_env()
    if args.command == "serve":
        import uvicorn

        from neraium_poly.ops.api import create_app
        from neraium_poly.ops.archive import PublicArchiveRuntime

        runtime = PublicArchiveRuntime(args.database) if args.database else None

        uvicorn.run(
            create_app(runtime=runtime, frontend_path=Path("frontend/dist")), host="127.0.0.1", port=args.port
        )
    elif args.command == "scenario":
        from neraium_poly.ops.runtime import ResearchRuntime

        runtime = ResearchRuntime()
        runtime.run_scenario()
        payload = json.dumps(runtime.state(), indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n")
        else:
            print(payload)
    else:
        import asyncio

        from neraium_poly.ops.collect import collect

        asyncio.run(
            collect(
                args.output or args.database or Path("data/public.sqlite"),
                cycles=args.cycles,
                interval=args.interval,
            )
        )


if __name__ == "__main__":
    main()
