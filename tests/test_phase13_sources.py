"""Controlled source fixtures are not historical research evidence."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from neraium_poly.research.phase13 import sources
from neraium_poly.research.phase13.contracts import SourceArtifact

NOW = datetime(2026, 11, 6, 6, tzinfo=UTC)
CSV = (
    b"game_id,season,game_type,gameday,gametime,home_team,away_team,home_score,away_score,result,total,home_moneyline\n"
    b"2026_01_DET_MIA,2026,REG,2026-09-01,13:00,MIA,DET,20,24,-4,44,-999\n"
    b"2026_09_DET_MIA,2026,REG,2026-11-08,13:00,MIA,DET,,,,,-999\n"
)


def artifact(raw=CSV):
    return SourceArtifact(
        provider=sources.PROVIDER,
        source_id="123",
        source_url=sources.CSV_URL,
        source_timestamp=NOW - timedelta(hours=1),
        retrieved_at=NOW,
        available_at=NOW,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        raw_path="games.csv",
        quality="qualified",
    )


def client(raw=CSV, *, status=200, redirect=None, license_text=b"Attribution 4.0 International\n"):
    metadata = {
        "assets": [
            {
                "id": 123,
                "name": "games.csv",
                "browser_download_url": sources.CSV_URL,
                "size": len(raw),
                "updated_at": (NOW - timedelta(hours=1)).isoformat(),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ]
    }

    def handler(request):
        if str(request.url) == sources.LICENSE:
            return httpx.Response(200, content=license_text)
        if str(request.url) == sources.RELEASE:
            return httpx.Response(200, json=metadata)
        if redirect:
            return httpx.Response(302, headers={"location": redirect})
        return httpx.Response(status, content=raw)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_availability_scores_and_odds_exclusion():
    games, rejected = sources.parse_nfl_csv(CSV, artifact(), minimum_season=2024)
    assert not rejected
    assert len(games) == 2
    assert games[0].status == "final" and games[0].result_observed_at == NOW
    assert games[1].starts_at == datetime(2026, 11, 8, 18, tzinfo=UTC)
    assert games[1].status == "scheduled"
    assert all(g.available_at == NOW for g in games)
    assert "moneyline" not in games[0].model_dump_json()


@pytest.mark.asyncio
async def test_acquire_replay_immutable_and_raw_hash(tmp_path):
    async with client() as http:
        original = await sources.collect_sports(tmp_path, client=http, clock=lambda: NOW)
    replay = sources.load_sports(tmp_path)
    assert original == replay
    assert original["report"]["official_results"] is False
    assert original["report"]["games"] == 2
    async with client(status=503) as http:
        assert await sources.collect_sports(tmp_path, client=http, clock=lambda: NOW) == original
    path = tmp_path / "games.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="corrupt_raw"):
        sources.load_sports(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"redirect": "http://169.254.169.254/latest/meta-data"}, "redirect_not_allowed"),
        ({"license_text": b"restricted"}, "license_changed"),
        ({"status": 429}, "429"),
    ],
)
async def test_fail_closed_provider_restrictions(tmp_path, changes, reason):
    async with client(**changes) as http:
        with pytest.raises((ValueError, httpx.HTTPStatusError), match=reason):
            await sources.collect_sports(tmp_path, client=http, clock=lambda: NOW)
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.asyncio
async def test_response_budget(tmp_path):
    async with client(raw=b"x" * (sources.MAX_RESPONSE_BYTES + 1)) as http:
        with pytest.raises(ValueError, match="asset_budget"):
            await sources.collect_sports(tmp_path, client=http, clock=lambda: NOW)


def test_duplicate_identity_is_fatal():
    raw = CSV + CSV.splitlines(keepends=True)[1]
    with pytest.raises(ValueError, match="duplicate_game"):
        sources.parse_nfl_csv(raw, artifact(raw), minimum_season=2024)


def test_incomplete_scores_unknown_past_and_contradiction():
    raw = CSV.replace(b",20,24,-4,44,", b",20,24,5,44,")
    games, reasons = sources.parse_nfl_csv(raw, artifact(raw), minimum_season=2024)
    assert len(games) == 1 and reasons == {"contradictory_score_result_total": 1}
    raw = CSV.replace(b",20,24,-4,44,", b",,,,,")
    games, _ = sources.parse_nfl_csv(raw, artifact(raw), minimum_season=2024)
    assert games[0].status == "unknown" and games[0].result_observed_at is None


def test_symlinks_fail_before_write(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="storage_alias"):
        sources.load_sports(alias)


@pytest.mark.asyncio
async def test_manifest_tamper_and_nested_alias(tmp_path):
    async with client() as http:
        await sources.collect_sports(tmp_path, client=http, clock=lambda: NOW)
    p = tmp_path / "manifest.json"
    m = json.loads(p.read_text())
    m["artifacts"][-1]["raw_path"] = "../outside"
    p.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="artifact_identity"):
        sources.load_sports(tmp_path)
    (tmp_path / "alias").symlink_to(tmp_path / "games.csv")
    with pytest.raises(ValueError, match="storage_alias"):
        sources.load_sports(tmp_path)


def test_unknown_schema_cannot_be_normalized():
    raw = b"game_id,season\nx,2026\n"
    with pytest.raises(ValueError, match="schema_changed"):
        sources.parse_nfl_csv(raw, artifact(raw), minimum_season=2024)


def test_future_or_backdated_source_availability():
    with pytest.raises(ValueError, match="earlier availability"):
        artifact().model_validate({**artifact().model_dump(), "available_at": NOW - timedelta(days=1)})
    with pytest.raises(ValueError, match="future source"):
        artifact().model_validate({**artifact().model_dump(), "source_timestamp": NOW + timedelta(days=1)})
