"""Delivery B backfill acceptance: reviewed state must equal the immutable state written.

Run only through scripts/test-codex.ps1, sequentially against zargar_test_codex.
This file was written for the parent reviewer to run; its author did not execute it.
The existing first-PR test covers successful apply/reapply and unknown availability.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DB_URL
from zargar.db import make_engine, make_session_factory
from zargar.models import (
    TechniqueMethodNote,
    TechniqueSourceArtifact,
    TechniqueSourceJob,
    TechniqueSourceRevision,
)
from zargar.tools import em_source_backfill as backfill


# Fail during collection, before fresh_db can drop/create anything on a wrong DB.
_url = make_url(TEST_DB_URL)
if not (
    _url.database == "zargar_test_codex"
    and _url.host in {"127.0.0.1", "localhost", "::1"}
    and _url.port == 5433
):
    raise RuntimeError("These backfill regressions require loopback:5433/zargar_test_codex")

pytestmark = pytest.mark.usefixtures("fresh_db")


async def _seed(sf, note_id="backfill-evidence"):
    async with sf() as session:
        session.add(TechniqueMethodNote(
            id=note_id, technique="enhanced_market", message_id="backfill-msg-1",
            channel_id="em-review", channel_name="EM review", author="EnhancedMarket",
            kind="video", status="checked", text="Original chart and video caption",
            images=["https://example.invalid/original-chart.png"],
            media_url="https://example.invalid/original-video",
            transcript="Original transcript: watch resistance, no stated stop.",
            extraction={"summary": "Original extraction", "symbols": ["MSFT"]},
        ))
        await session.commit()
    return note_id


async def _counts(sf):
    async with sf() as session:
        return tuple([
            (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (
                TechniqueMethodNote, TechniqueSourceRevision,
                TechniqueSourceArtifact, TechniqueSourceJob,
            )
        ])


async def _require_refusal_without_writes(sf, manifest, reason):
    try:
        result = await backfill.apply(sf, manifest)
    except ValueError:
        # A typed invalid/stale-manifest exception is also an explicit refusal.
        result = 0
    assert result == 0, reason
    assert await _counts(sf) == (1, 0, 0, 0), "Refusal must leave all legacy/source rows intact"


def test_dry_run_is_read_only_and_apply_rejects_invalid_manifest_digest():
    async def scenario():
        db = make_engine(TEST_DB_URL)
        sf = make_session_factory(db)
        try:
            await _seed(sf)
            before = await _counts(sf)
            manifest = await backfill.build_manifest(sf)
            assert len(manifest["items"]) == 1
            assert await _counts(sf) == before == (1, 0, 0, 0), "Dry run must be read-only"
            assert all(a["availability"] == "unknown" for a in manifest["items"][0]["artifacts"])
            invalid = deepcopy(manifest)
            invalid["planHash"] = "not-the-reviewed-manifest-digest"
            await _require_refusal_without_writes(
                sf, invalid, "Apply must verify its manifest digest before writing immutable records",
            )
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_apply_rejects_changed_artifact_payloads_with_unchanged_source_caption():
    async def scenario():
        db = make_engine(TEST_DB_URL)
        sf = make_session_factory(db)
        try:
            note_id = await _seed(sf)
            manifest = await backfill.build_manifest(sf)
            async with sf() as session:
                note = await session.get(TechniqueMethodNote, note_id)
                note.transcript = "Corrected transcript: the prior interpretation was wrong."
                note.extraction = {"summary": "Corrected extraction", "symbols": ["AAPL"]}
                await session.commit()
            await _require_refusal_without_writes(
                sf, manifest,
                "Unchanged text/images do not authorize copying newly changed artifacts under old input hashes",
            )
        finally:
            await db.dispose()
    asyncio.run(scenario())


def test_apply_rechecks_source_after_preflight_under_the_row_lock(monkeypatch):
    async def scenario():
        db = make_engine(TEST_DB_URL)
        sf = make_session_factory(db)
        try:
            note_id = await _seed(sf)
            manifest = await backfill.build_manifest(sf)
            original_build = backfill.build_manifest
            changed_after_preflight = False

            async def preflight_then_edit(session_factory):
                nonlocal changed_after_preflight
                snapshot = await original_build(session_factory)
                if not changed_after_preflight:
                    async with session_factory() as session:
                        note = await session.get(TechniqueMethodNote, note_id)
                        note.text = "Source changed after the preflight read"
                        note.images = ["https://example.invalid/replacement-chart.png"]
                        await session.commit()
                    changed_after_preflight = True
                return snapshot

            # Simulates a writer committing after apply's preflight read and before
            # its SELECT FOR UPDATE. The apply must validate the locked state too.
            monkeypatch.setattr(backfill, "build_manifest", preflight_then_edit)
            await _require_refusal_without_writes(
                sf, manifest,
                "A post-preflight edit must not become revision text with the old manifest content hash",
            )
            assert changed_after_preflight, "The source-edit boundary must actually be exercised"
        finally:
            await db.dispose()
    asyncio.run(scenario())
