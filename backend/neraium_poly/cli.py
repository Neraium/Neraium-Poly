"""Local commands are paper-only; collect reads public data."""

import argparse
import json
from pathlib import Path

from neraium_poly.settings import Settings


def main():
    parser = argparse.ArgumentParser(description="Neraium-Poly paper research")
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "scenario",
            "collect",
            "paper-live",
            "strategy-validate",
            "strategy-package",
            "research-acquire",
            "research-evaluate",
            "research-cycle",
            "research-audit",
            "strategy-approve",
            "strategy-status",
            "strategy-revoke",
        ],
    )
    parser.add_argument("--port", type=int, default=18740)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--cycles", type=int, default=1, help="Collection rounds; 0 runs until interrupted")
    parser.add_argument("--interval", type=float, default=30, help="Collection interval seconds, minimum 5")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data/paper-live"))
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report-id")
    parser.add_argument("--actor")
    parser.add_argument("--owner-public-key", type=Path)
    parser.add_argument("--owner-request-id")
    parser.add_argument("--owner-signature", type=Path)
    parser.add_argument("--research-dir", type=Path, default=Path("data/phase8-history"))
    parser.add_argument("--max-events", type=int, default=250)
    parser.add_argument("--max-history-requests", type=int, default=50)
    parser.add_argument("--event-first", action="store_true")
    parser.add_argument("--reason", default="operator revoked")
    args = parser.parse_args()
    Settings.from_env()
    if args.command == "research-audit":
        from neraium_poly.research.public_archive import audit_public_archive

        result = audit_public_archive(args.research_dir)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    elif args.command.startswith("research-"):
        from neraium_poly.research.evaluation import write_report
        from neraium_poly.research.history import HistoryPipeline, completeness_report, load_bundle

        if args.command in {"research-acquire", "research-cycle"}:
            import asyncio

            async def acquire():
                pipeline = HistoryPipeline(args.research_dir)
                try:
                    return await pipeline.acquire(
                        max_events=args.max_events,
                        max_history_requests=args.max_history_requests,
                        archive_path=args.database,
                        event_first=args.event_first,
                    )
                finally:
                    await pipeline.close()

            bundle = asyncio.run(acquire())
        else:
            bundle = load_bundle(args.research_dir)
        if args.command in {"research-evaluate", "research-cycle"}:
            target = args.output or Path("data/paper-live/research/report.json")
            result = write_report(bundle, target)
            print(
                json.dumps(
                    {
                        "dataset_hash": result["dataset_hash"],
                        "coverage": result["coverage"],
                        "certification": result["certification"],
                        "report": str(target),
                    },
                    indent=2,
                )
            )
        else:
            print(json.dumps(completeness_report(bundle), indent=2))
    elif args.command == "paper-live":
        import asyncio

        from neraium_poly.ops.live import serve_live
        from neraium_poly.ops.live_config import LivePaperConfig

        config = (
            LivePaperConfig.model_validate_json(args.config.read_text())
            if args.config
            else LivePaperConfig(data_dir=args.data_dir)
        )
        asyncio.run(serve_live(config))
    elif args.command.startswith("strategy-"):
        from datetime import UTC, datetime

        from neraium_poly.validation import ValidationStore

        args.data_dir.mkdir(parents=True, exist_ok=True)
        store = ValidationStore(
            str(args.data_dir / "approval.sqlite"), owner_public_key=args.owner_public_key
        )
        now = datetime.now(UTC)
        try:
            if args.command == "strategy-status":
                result = store.status(now)
            elif args.command == "strategy-validate":
                if not args.dataset or not args.manifest:
                    parser.error("strategy-validate requires --dataset and --manifest")
                report = store.validate(args.dataset, args.manifest, now)
                result = report.model_dump(mode="json")
            elif args.command == "strategy-package":
                if not args.report_id or not args.output:
                    parser.error("strategy-package requires --report-id and --output")
                from neraium_poly.owner import canonical

                result = store.prepare_owner_request(args.report_id, now)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(canonical(result))
            elif args.command == "strategy-approve":
                if not args.report_id or not args.actor:
                    parser.error("strategy-approve requires --report-id and --actor")
                result = {
                    "activation_id": store.approve(
                        args.report_id,
                        args.actor,
                        now,
                        owner_request_id=args.owner_request_id,
                        owner_signature=args.owner_signature.read_bytes() if args.owner_signature else None,
                    )
                }
            else:
                if not args.actor:
                    parser.error("strategy-revoke requires --actor")
                store.revoke(args.actor, now, args.reason)
                result = {"revoked": True}
            print(json.dumps(result, indent=2, default=str))
        finally:
            store.close()
    elif args.command == "serve":
        import uvicorn

        from neraium_poly.ops.api import create_app
        from neraium_poly.ops.archive import PublicArchiveRuntime

        runtime = PublicArchiveRuntime(args.database) if args.database else None

        uvicorn.run(
            create_app(runtime=runtime, frontend_path=Path("frontend/dist"), local_port=args.port),
            host="127.0.0.1",
            port=args.port,
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
