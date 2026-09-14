"""EM source revisions, artifacts and jobs - Delivery B, first PR (2026-09-14; design in
docs/techniques/enhanced-market/reviews/DELIVERY-B-DESIGN-2026-09-14.md, "Revision after the reviewers' answers").

Three tables, three mutability classes:
- `technique_source_revisions` - IMMUTABLE observations of the source: one row per distinct accepted
  source state (create, edit, delete, restore; `A -> B -> A` is three revisions). Identical transport
  redelivery is a receipt, never a revision. No transcript, no usability on this table.
- `technique_source_artifacts` - APPEND-ONLY derived outputs (transcript | extraction | scenarios) keyed by
  (revision, kind, input hash, config hash): the idempotent OUTPUT KEY. `first_usable_at` of anything built
  from an artifact is that artifact's `completed_at` - a fact, never backfilled from `updated_at`.
- `technique_source_jobs` - MUTABLE progress per revision: stage, lease, FENCE TOKEN, per-item checkpoints.

The two implementation contracts the reviewers required of this PR:
1. Ordering + safe partial merge (`record_delivery`): the source's own edit timestamp orders deliveries,
   the gateway sequence breaks ties; an OLDER delivery never replaces a newer accepted state (it is
   recorded as `stale`, nothing changes); a PARTIAL payload (text/images absent = None) keeps the prior
   accepted values for the absent fields - absence is "not in this payload", never "cleared".
2. Atomic output + checkpoint (`checkpoint`): the artifact row and the job checkpoint are staged in ONE
   session and committed together; the artifact insert is idempotent by its output key, so a crash between
   an output and its checkpoint is recovered by re-deriving the SAME key (the existing row is reused, never
   duplicated). A worker whose lease expired holds a stale fence token: its checkpoint is refused
   (`FenceMismatch`) and nothing it staged is committed.

EM-only. Nothing here places, sizes or arms anything: candidates that will later reference these rows
carry `origin = scenario:<id>` and the runner refuses to arm them (`PlanRunner.arm`, order-free boundary).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select

from ..domain import new_id
from ..models import TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceJob, TechniqueSourceRevision

TECHNIQUE = "enhanced_market"
STAGES = ("received", "transcribed", "extracted", "board_checked", "scenarios_built", "done")
ARTIFACT_KINDS = ("transcript", "extraction", "scenarios")
DEFAULT_LEASE_SECONDS = 15 * 60


class FenceMismatch(RuntimeError):
    """The worker's lease expired and another worker (or a resume) holds the job: its writes are refused."""


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(s) -> dt.datetime | None:
    if not s:
        return None
    if isinstance(s, dt.datetime):
        return s if s.tzinfo else s.replace(tzinfo=dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def content_hash(text: str | None, attachments: list | None, *, deleted: bool = False) -> str:
    """The identity of one source STATE: verbatim text + the attachment set (+ the deletion marker)."""
    body = json.dumps({"text": str(text or ""), "attachments": sorted(str(a) for a in (attachments or [])),
                       "deleted": bool(deleted)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def artifact_key(revision_id: str, kind: str, input_hash: str, config_hash: str) -> str:
    return hashlib.sha256(f"{revision_id}|{kind}|{input_hash}|{config_hash}".encode("utf-8")).hexdigest()[:32]


def revision_dict(r: TechniqueSourceRevision) -> dict:
    return {"id": r.id, "noteId": r.note_id, "revision": r.revision, "kind": r.kind, "deleted": bool(r.deleted),
            "sourceEditedAt": r.source_edited_at.isoformat() if r.source_edited_at else None,
            "publishedAt": r.published_at.isoformat() if r.published_at else None,
            "receivedAt": r.received_at.isoformat() if r.received_at else None,
            "gatewaySeq": r.gateway_seq, "authorId": r.author_id, "authorName": r.author_name,
            "channelId": r.channel_id, "channelName": r.channel_name, "contentHash": r.content_hash,
            "supersedes": r.supersedes, "attachments": list(r.attachments or [])}


def job_dict(j: TechniqueSourceJob) -> dict:
    return {"id": j.id, "noteId": j.note_id, "revisionId": j.revision_id, "stage": j.stage, "attempts": j.attempts,
            "leaseOwner": j.lease_owner, "leaseUntil": j.lease_until.isoformat() if j.lease_until else None,
            "fenceToken": j.fence_token, "checkpoint": list(j.checkpoint or []), "outcome": j.outcome,
            "error": j.error}


# ------------------------------------------------------------------ revisions (contract 1)
async def current_revision(session, note_id: str) -> TechniqueSourceRevision | None:
    return (await session.execute(
        select(TechniqueSourceRevision).where(TechniqueSourceRevision.note_id == note_id)
        .order_by(TechniqueSourceRevision.revision.desc()).limit(1))).scalars().first()


async def record_delivery(session, *, note_id: str, payload: dict, kind: str = "create",
                          received_at: dt.datetime | None = None, gateway_seq: int | None = None) -> dict:
    """One delivery of source state for `note_id` (the note row is locked for the duration so revisions
    are numbered serially). Stages the revision (and its job) in the CALLER's session - the caller commits.

    Returns {"outcome": recorded | redelivery | stale, "revision": n, "revisionId", "created": bool, ...}.
    - recorded:   a new distinct source state -> revision n+1 (kind create | edit | delete | restore)
    - redelivery: identical content to the current accepted state -> no row (a receipt for the caller)
    - stale:      the delivery is OLDER than the current accepted state (source edit time, then gateway
                  sequence) -> refused, nothing changes; the caller may journal it
    """
    kind = str(kind or "create")
    note = await session.get(TechniqueMethodNote, note_id, with_for_update=True)
    if note is None:
        raise KeyError(note_id)
    cur = await current_revision(session, note_id)
    edited = parse_ts(payload.get("editedAt"))
    published = parse_ts(payload.get("postedAt")) or (cur.published_at if cur else None)
    if cur is not None:
        cur_mark = cur.source_edited_at or cur.published_at
        if edited is not None and cur_mark is not None and edited < cur_mark:
            return {"outcome": "stale", "revision": cur.revision, "revisionId": cur.id, "created": False,
                    "why": f"delivery edited {edited.isoformat()} is older than the accepted {cur_mark.isoformat()}"}
        if edited is None and gateway_seq is not None and cur.gateway_seq is not None and gateway_seq < cur.gateway_seq:
            return {"outcome": "stale", "revision": cur.revision, "revisionId": cur.id, "created": False,
                    "why": f"gateway sequence {gateway_seq} is older than the accepted {cur.gateway_seq}"}
    # partial merge: an absent field (None) means "not in this payload" - keep the accepted value
    text = payload.get("text")
    images = payload.get("images")
    if cur is not None:
        if text is None:
            text = cur.text
        if images is None:
            images = list(cur.attachments or [])
    text = str(text or "")
    images = [str(u) for u in (images or [])][:12]
    deleted = kind == "delete"
    h = content_hash(text, images, deleted=deleted)
    if cur is not None and cur.content_hash == h:
        return {"outcome": "redelivery", "revision": cur.revision, "revisionId": cur.id, "created": False}
    n = (cur.revision + 1) if cur is not None else 1
    if cur is None:
        rkind = "create"
    elif deleted:
        rkind = "delete"
    elif cur.deleted:
        rkind = "restore"
    else:
        rkind = "edit"
    rev = TechniqueSourceRevision(
        id=new_id(), note_id=note_id, technique=TECHNIQUE, revision=n, kind=rkind, deleted=deleted,
        source_edited_at=edited, published_at=published, received_at=received_at or utcnow(), gateway_seq=gateway_seq,
        author_id=(str(payload.get("authorId")) if payload.get("authorId") else (cur.author_id if cur else None)),
        author_name=str(payload.get("author") or (cur.author_name if cur else "") or "")[:128],
        channel_id=str(payload.get("channelId") or (cur.channel_id if cur else "") or ""),
        channel_name=str(payload.get("channelName") or (cur.channel_name if cur else "") or "")[:128],
        text=text, attachments=images, content_hash=h, supersedes=(cur.id if cur else None))
    session.add(rev)
    await session.flush()
    session.add(TechniqueSourceJob(id=new_id(), note_id=note_id, revision_id=rev.id, technique=TECHNIQUE,
                                   stage="received", outcome="in_progress", fence_token=0, checkpoint=[]))
    await session.flush()
    return {"outcome": "recorded", "revision": n, "revisionId": rev.id, "created": True, "kind": rkind,
            "supersedes": rev.supersedes}


async def revisions_for(session, note_id: str) -> list[dict]:
    rows = (await session.execute(select(TechniqueSourceRevision).where(TechniqueSourceRevision.note_id == note_id)
                                  .order_by(TechniqueSourceRevision.revision.asc()))).scalars().all()
    return [revision_dict(r) for r in rows]


# ------------------------------------------------------------------ jobs and artifacts (contract 2)
async def resume_unfinished(session, *, owner: str, now: dt.datetime | None = None,
                            lease_seconds: int = DEFAULT_LEASE_SECONDS, limit: int = 50) -> list[dict]:
    """Every job that is not done and whose lease is free or expired: re-lease it to `owner` under a NEW
    fence token at its recorded stage (never from the beginning - the checkpoint list is kept). A worker
    that still holds an expired lease learns about it when its next checkpoint is refused."""
    now = now or utcnow()
    rows = (await session.execute(
        select(TechniqueSourceJob).where(TechniqueSourceJob.outcome.in_(("in_progress", "retryable")))
        .order_by(TechniqueSourceJob.created_at.asc()).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    out = []
    for j in rows:
        if j.lease_until is not None and j.lease_until > now and j.lease_owner:
            continue                                   # a live lease
        if j.next_due_at is not None and j.next_due_at > now:
            continue                                   # backing off
        j.fence_token = int(j.fence_token or 0) + 1
        j.lease_owner = owner
        j.lease_until = now + dt.timedelta(seconds=lease_seconds)
        j.attempts = int(j.attempts or 0) + 1
        j.outcome = "in_progress"
        j.updated_at = now
        out.append(job_dict(j))
    await session.flush()
    return out


async def checkpoint(session, *, job_id: str, fence_token: int, item_key: str, artifact: dict | None = None,
                     stage: str | None = None, outcome: str | None = None, error: str | None = None,
                     now: dt.datetime | None = None) -> dict:
    """Record one completed item for a job - and, when it produced an output, the artifact row - in the
    CALLER's session so one commit carries both. Refused (`FenceMismatch`) unless `fence_token` is the
    job's current token. The artifact is idempotent by its output key: an existing row with the same
    (revision, kind, input hash, config hash) is reused, never duplicated.

    `artifact`: {"kind", "inputHash", "configHash", "payload", "version"?, "completedAt"?}
    """
    now = now or utcnow()
    job = await session.get(TechniqueSourceJob, job_id, with_for_update=True)
    if job is None:
        raise KeyError(job_id)
    if int(job.fence_token or 0) != int(fence_token):
        raise FenceMismatch(f"job {job_id[:8]}: fence {fence_token} is not current ({job.fence_token}) - "
                            f"the lease moved to {job.lease_owner!r}; nothing written")
    art_row = None
    reused = False
    if artifact:
        kind = str(artifact["kind"])
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"unknown artifact kind {kind!r}")
        key = artifact_key(job.revision_id, kind, str(artifact["inputHash"]), str(artifact["configHash"]))
        art_row = await session.get(TechniqueSourceArtifact, key)
        if art_row is None:
            art_row = TechniqueSourceArtifact(
                id=key, revision_id=job.revision_id, note_id=job.note_id, technique=TECHNIQUE, kind=kind,
                version=int(artifact.get("version") or 1), config_hash=str(artifact["configHash"]),
                input_hash=str(artifact["inputHash"]), payload=dict(artifact.get("payload") or {}),
                completed_at=parse_ts(artifact.get("completedAt")) or now)
            session.add(art_row)
        else:
            reused = True
    cp = [str(x) for x in (job.checkpoint or [])]
    if item_key not in cp:
        cp.append(item_key)
    job.checkpoint = cp                                 # a new list: the ORM records the change
    if stage:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        job.stage = stage
    if outcome:
        job.outcome = outcome
        if outcome in ("done", "permanent"):
            job.lease_owner = None
            job.lease_until = None
    if error is not None:
        job.error = error[:500]
    job.updated_at = now
    await session.flush()
    return {"job": job_dict(job), "artifactId": (art_row.id if art_row is not None else None), "artifactReused": reused}


async def artifacts_for(session, revision_id: str) -> list[dict]:
    rows = (await session.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.revision_id == revision_id)
                                  .order_by(TechniqueSourceArtifact.created_at.asc()))).scalars().all()
    return [{"id": a.id, "kind": a.kind, "version": a.version, "inputHash": a.input_hash, "configHash": a.config_hash,
             "completedAt": a.completed_at.isoformat() if a.completed_at else None,
             "availability": ("unknown" if a.completed_at is None else "known")} for a in rows]


# the order-free boundary lives in the shared runner: `zargar/execution/origins.py::scenario_origin`
from ..execution.origins import scenario_origin  # noqa: E402,F401 - re-exported for EM callers
