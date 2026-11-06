"""Bounded openly licensed NFL source snapshots with replayable raw provenance.

nflverse supplies a derived community dataset, not an official NFL result oracle.
Only actual retrieval establishes availability here. No historical publication
or finality timing is inferred from a game date, Git timestamp, or final score.
"""

import asyncio
import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

from neraium_poly.research.phase13.contracts import SourceArtifact, SportsGame

PROVIDER = "nflverse/nflverse-data"
RELEASE = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/schedules"
LICENSE = "https://raw.githubusercontent.com/nflverse/nflverse-data/main/LICENSE.md"
CSV_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
MAX_RESPONSE_BYTES = 4 * 1024**2
MAX_SNAPSHOT_BYTES = 12 * 1024**2
MAX_GAMES = 30000
TEAMS = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams",
    "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _safe_root(directory, *, create=False):
    path = Path(directory)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("sports_source_storage_alias")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("sports_source_directory_missing")
    files = list(path.rglob("*"))
    if len(files) > 100 or any(p.is_symlink() or (p.is_file() and p.stat().st_nlink != 1) for p in files):
        raise ValueError("sports_source_storage_alias_or_count")
    if sum(p.stat().st_size for p in files if p.is_file()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("sports_source_snapshot_budget")
    return path


async def _get(client, url, *, maximum=MAX_RESPONSE_BYTES):
    """At most four GETs for HTTPS redirects, never credentials or arbitrary hosts."""
    allowed = {
        "api.github.com",
        "github.com",
        "raw.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
    for _ in range(4):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in allowed or parts.username or parts.password:
            raise ValueError("sports_source_redirect_not_allowed")
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            response.raise_for_status()  # 429/403 withhold; caller schedules retry, no tight loop.
            if int(response.headers.get("content-length", "0")) > maximum:
                raise ValueError("sports_source_response_budget")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > maximum:
                    raise ValueError("sports_source_response_budget")
            return bytes(body)
    raise ValueError("sports_source_redirect_limit")


def parse_nfl_csv(raw, artifact, *, minimum_season):
    """Normalize only identities, schedules and scores; all market/odds columns ignored."""
    if hashlib.sha256(raw).hexdigest() != artifact.content_sha256 or artifact.quality != "qualified":
        raise ValueError("sports_source_hash_or_quality")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {
        "game_id",
        "season",
        "game_type",
        "gameday",
        "gametime",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "result",
        "total",
    }
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("nfl_schedule_schema_changed")
    games, rejected, seen = [], Counter(), set()
    for index, row in enumerate(reader):
        if index >= MAX_GAMES:
            raise ValueError("nfl_schedule_row_budget")
        try:
            season = int(row["season"])
            if season < minimum_season or row["game_type"] not in {"REG", "WC", "DIV", "CON", "SB"}:
                continue
            if season > artifact.retrieved_at.year + 1:
                raise ValueError("unsupported_future_season")
            if not row["game_id"] or row["game_id"] in seen:
                raise ValueError("duplicate_game_identity")
            seen.add(row["game_id"])
            if row["home_team"] not in TEAMS or row["away_team"] not in TEAMS:
                raise ValueError("unknown_participant")
            # nflverse gametime is US Eastern per its published schedule dictionary.
            local = datetime.strptime(row["gameday"] + " " + row["gametime"], "%Y-%m-%d %H:%M")
            starts = local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
            scores = [row["home_score"].strip(), row["away_score"].strip()]
            if bool(scores[0]) != bool(scores[1]):
                raise ValueError("incomplete_score")
            if all(scores):
                if starts + timedelta(hours=1) >= artifact.available_at:
                    raise ValueError("implausible_future_or_in_progress_final_score")
                home, away = (int(x) for x in scores)
                if int(row["result"]) != home - away or int(row["total"]) != home + away:
                    raise ValueError("contradictory_score_result_total")
                status, observed = "final", artifact.available_at
            else:
                home = away = observed = None
                # This CSV has no cancellation/postponement/finality status field.
                # Past empty scores remain unknown, never guessed final or scheduled.
                status = "scheduled" if starts > artifact.available_at else "unknown"
            games.append(
                SportsGame(
                    provider=PROVIDER,
                    game_id=row["game_id"],
                    league="NFL",
                    home_id=row["home_team"],
                    away_id=row["away_team"],
                    home_name=TEAMS[row["home_team"]],
                    away_name=TEAMS[row["away_team"]],
                    starts_at=starts,
                    status=status,
                    home_score=home,
                    away_score=away,
                    result_observed_at=observed,
                    artifact_sha256=artifact.content_sha256,
                    available_at=artifact.available_at,
                )
            )
        except (ValueError, KeyError) as error:
            if str(error) == "duplicate_game_identity":
                raise ValueError("duplicate_game_identity") from error
            rejected[str(error)[:100]] += 1
    return sorted(games, key=lambda g: (g.starts_at, g.game_id)), dict(rejected)


async def collect_sports(directory, *, clock=None, client=None, leagues=("NFL",)):
    """Acquire an immutable bounded snapshot; existing snapshot is replayed, never overwritten.

    The caller owns aggregate archive limits and must use a new directory per
    refresh. This adapter caps each snapshot and preserves data at exhaustion.
    """
    clock = clock or (lambda: datetime.now(UTC))
    root = _safe_root(directory, create=True)
    if (root / "manifest.json").exists():
        return load_sports(root)
    if any(root.iterdir()):
        raise ValueError("sports_source_partial_snapshot_requires_new_directory")
    if not set(leagues).issubset({"NBA", "NFL"}) or "NFL" not in leagues:
        raise ValueError("sports_source_no_licensed_provider")
    if shutil.disk_usage(root).free < 8 * 1024**3:
        raise ValueError("sports_source_free_disk_floor")
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=20,
        headers={
            "User-Agent": "Neraium-Poly/0.1 public-research-source-observer",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        license_bytes = await _get(client, LICENSE, maximum=64 * 1024)
        if not license_bytes.startswith(b"Attribution 4.0 International"):
            raise ValueError("nflverse_license_changed_or_missing")
        await asyncio.sleep(0.25)
        metadata = await _get(client, RELEASE, maximum=256 * 1024)
        release = json.loads(metadata)
        assets = [a for a in release.get("assets", []) if a.get("name") == "games.csv"]
        if len(assets) != 1 or assets[0].get("browser_download_url") != CSV_URL:
            raise ValueError("nflverse_release_identity_changed")
        asset = assets[0]
        if not 0 < asset.get("size", 0) <= MAX_RESPONSE_BYTES:
            raise ValueError("nflverse_release_asset_budget")
        await asyncio.sleep(0.25)
        raw = await _get(client, CSV_URL)
        observed = clock()
        source_time = datetime.fromisoformat(asset["updated_at"])
        expected = asset.get("digest")
        if expected != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise ValueError("nflverse_release_digest_changed_during_acquisition")
        bodies = {"license.txt": license_bytes, "release.json": metadata, "games.csv": raw}
        artifacts = []
        for name, body in bodies.items():
            artifacts.append(
                SourceArtifact(
                    provider=PROVIDER,
                    source_id=(str(asset["id"]) if name == "games.csv" else name),
                    source_url={"license.txt": LICENSE, "release.json": RELEASE, "games.csv": CSV_URL}[name],
                    source_timestamp=source_time if name == "games.csv" else None,
                    retrieved_at=observed,
                    available_at=observed,
                    content_sha256=hashlib.sha256(body).hexdigest(),
                    raw_path=name,
                    quality="qualified",
                    missingness=(
                        "row_publication_times",
                        "official_result_finality",
                        "cancellation_status",
                        "injuries",
                        "lineups",
                    ),
                )
            )
        games, rejected = parse_nfl_csv(raw, artifacts[-1], minimum_season=observed.year - 2)
        report = {
            "provider": PROVIDER,
            "license": "CC-BY-4.0",
            "attribution": "nflverse contributors; Lee Sharpe schedules; normalized fields, odds discarded",
            "license_url": "https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md",
            "source_url": CSV_URL,
            "collected_at": observed.isoformat(),
            "games": len(games),
            "statuses": dict(Counter(g.status for g in games)),
            "rejected_rows": rejected,
            "minimum_season": observed.year - 2,
            "source_updated_at": source_time.isoformat(),
            "availability": "First observed retrieval, not historical event time or publisher update time",
            "official_results": False,
            "result_status_semantics": "publisher_reported_scores_not_official_finality",
            "certification_authority": False,
            "withheld_providers": {
                "NBA": "NBA terms prohibit gambling/database use absent consent",
                "NFL.com": "No licensed official automated result access configured",
                "ATP/esports": "No qualified provider configured",
            },
            "missingness": list(artifacts[-1].missingness),
        }
        manifest = {
            "schema_version": "1.0",
            "artifacts": [a.model_dump(mode="json") for a in artifacts],
            "report": report,
            "games_sha256": digest([g.model_dump(mode="json") for g in games]),
        }
        encoded = json.dumps(manifest, sort_keys=True, indent=2).encode()
        if sum(len(b) for b in bodies.values()) + len(encoded) > MAX_SNAPSHOT_BYTES:
            raise ValueError("sports_source_snapshot_budget")
        for name, body in bodies.items():
            with (root / name).open("xb") as f:
                f.write(body)
        with (root / "manifest.json").open("xb") as f:
            f.write(encoded)
        return {
            "artifacts": artifacts,
            "games": games,
            "report": report,
            "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
        }
    finally:
        if own:
            await client.aclose()


def load_sports(directory):
    """Verify exact raw hashes and parsed-game digest before returning research inputs."""
    root = _safe_root(directory)
    manifest_path = root / "manifest.json"
    if manifest_path.stat().st_size > 256 * 1024:
        raise ValueError("sports_source_manifest_budget")
    encoded = manifest_path.read_bytes()
    manifest = json.loads(encoded)
    if manifest.get("schema_version") != "1.0":
        raise ValueError("sports_source_manifest_version")
    artifacts = [SourceArtifact.model_validate(a) for a in manifest["artifacts"]]
    expected = {"license.txt": LICENSE, "release.json": RELEASE, "games.csv": CSV_URL}
    if len(artifacts) != 3 or {a.raw_path for a in artifacts} != set(expected):
        raise ValueError("sports_source_artifact_identity")
    raw = {}
    for artifact in artifacts:
        if (
            artifact.provider != PROVIDER
            or artifact.source_url != expected[artifact.raw_path]
            or artifact.quality != "qualified"
        ):
            raise ValueError("sports_source_provider_or_quality")
        path = root / artifact.raw_path
        if path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ValueError("sports_source_response_budget")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != artifact.content_sha256:
            raise ValueError("sports_source_corrupt_raw")
        raw[artifact.raw_path] = body
    if not raw["license.txt"].startswith(b"Attribution 4.0 International"):
        raise ValueError("nflverse_license_changed_or_missing")
    artifact = next(a for a in artifacts if a.raw_path == "games.csv")
    release = json.loads(raw["release.json"])
    assets = [a for a in release.get("assets", []) if a.get("name") == "games.csv"]
    if len(assets) != 1 or assets[0].get("browser_download_url") != CSV_URL:
        raise ValueError("nflverse_release_identity_changed")
    asset = assets[0]
    if (
        str(asset["id"]) != artifact.source_id
        or datetime.fromisoformat(asset["updated_at"]) != artifact.source_timestamp
        or asset.get("digest") != "sha256:" + artifact.content_sha256
    ):
        raise ValueError("nflverse_release_identity_or_digest")
    minimum = manifest["report"]["minimum_season"]
    if minimum != artifact.retrieved_at.year - 2:
        raise ValueError("nflverse_season_policy_changed")
    games, _ = parse_nfl_csv(raw["games.csv"], artifact, minimum_season=minimum)
    if digest([g.model_dump(mode="json") for g in games]) != manifest["games_sha256"]:
        raise ValueError("sports_source_normalization_changed")
    return {
        "artifacts": artifacts,
        "games": games,
        "report": manifest["report"],
        "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
    }
