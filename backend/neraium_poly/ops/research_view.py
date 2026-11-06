"""Read-only operational presentation of research reports, never activation."""

import json
from pathlib import Path


def research_view(path: Path | None, public_path: Path | None = None) -> dict:
    if path is None or not path.is_file():
        return {
            "status": "awaiting_evidence",
            "candidates": [],
            "models": [],
            "coverage": {},
            "certification": {
                "status": "blocked",
                "owner_approval_required": True,
                "deficiencies": ["no_research_report"],
            },
        }
    if path.stat().st_size > 2 * 1024 * 1024:
        return {
            "status": "invalid_report",
            "candidates": [],
            "models": [],
            "coverage": {},
            "error": "report_size_budget_exceeded",
        }
    try:
        report = json.loads(path.read_text())
        if not isinstance(report.get("candidates"), list) or not isinstance(report.get("coverage"), dict):
            raise TypeError("report schema")
        report["status"] = "research_only"
        report["activation_authority"] = False
        if public_path is not None and public_path.is_file() and public_path.stat().st_size < 2 * 1024 * 1024:
            report["publisher_archive"] = json.loads(public_path.read_text())
        return report
    except (OSError, ValueError, TypeError):
        return {
            "status": "invalid_report",
            "candidates": [],
            "models": [],
            "coverage": {},
            "error": "unreadable_or_malformed_research_report",
        }
