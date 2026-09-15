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

from sqlalchemy import or_, select

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
    # B-03: ONE explicit ordering key, kept on the note as the accepted WATERMARK independently of the
    # immutable content revisions: (event time, gateway sequence). Event time = the source's editedAt (else
    # postedAt on a create); a delivery without an event time is ordered by sequence alone; a delivery with
    # neither is UNORDERED and refused unless its content is identical (then it is a plain receipt).
    wm = dict((note.meta or {}).get("sourceWatermark") or {})
    wm_t, wm_seq = parse_ts(wm.get("at")), wm.get("seq")
    t = edited if edited is not None else (published if cur is None else None)
    if cur is not None:
        order = _compare_order(t, gateway_seq, wm_t, wm_seq)
        if order == "older":
            return {"outcome": "stale", "revision": cur.revision, "revisionId": cur.id, "created": False,
                    "why": (f"delivery ({t.isoformat() if t else 'no event time'}, seq {gateway_seq}) is older than the "
                            f"accepted watermark ({wm_t.isoformat() if wm_t else 'none'}, seq {wm_seq})")}
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
        # a newer identical state is not a new revision, but its ordering observation is kept (B-03)
        if order == "newer":
            _advance_watermark(note, t, gateway_seq)
        return {"outcome": "redelivery", "revision": cur.revision, "revisionId": cur.id, "created": False}
    if cur is not None and order == "unordered":
        return {"outcome": "unordered", "revision": cur.revision, "revisionId": cur.id, "created": False,
                "why": "a content change with neither an event time nor a gateway sequence cannot be ordered"}
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
    _advance_watermark(note, t, gateway_seq)
    await session.flush()
    return {"outcome": "recorded", "revision": n, "revisionId": rev.id, "created": True, "kind": rkind,
            "supersedes": rev.supersedes}


def _compare_order(t, seq, wm_t, wm_seq) -> str:
    """older | same | newer | unordered, for delivery (t, seq) against the accepted watermark (wm_t, wm_seq).
    Event time decides when both sides have one; equal times (or a missing delivery time) fall to the
    gateway sequence; with neither comparable the order is unknown."""
    if t is not None and wm_t is not None:
        if t < wm_t:
            return "older"
        if t > wm_t:
            return "newer"
    if seq is not None and wm_seq is not None:
        if int(seq) < int(wm_seq):
            return "older"
        if int(seq) > int(wm_seq):
            return "newer"
        return "same"
    if t is not None and wm_t is not None:
        return "same"                                    # equal times, no sequence on one side
    if t is not None and wm_t is None:
        return "newer"                                   # the watermark had no event time yet
    return "unordered"


def _advance_watermark(note: TechniqueMethodNote, t, seq) -> None:
    """The watermark is ONE accepted observation's (event time, sequence) pair - never a maximum taken
    per field across different events (P2, a55bced review: a newer event with a LOWER sequence, e.g. after
    a gateway sequence reset, must not inherit the older event's larger sequence, or its own later
    same-time updates are discarded). A newer event time replaces the pair; the same event time keeps
    the larger sequence; an event without a time advances the sequence only."""
    wm = dict((note.meta or {}).get("sourceWatermark") or {})
    wm_t = parse_ts(wm.get("at"))
    if t is not None and (wm_t is None or t > wm_t):
        wm = {"at": t.isoformat(), "seq": (int(seq) if seq is not None else None)}
    elif seq is not None and (wm.get("seq") is None or int(seq) > int(wm["seq"])):
        wm["seq"] = int(seq)
        if t is not None and wm_t is None:
            wm["at"] = t.isoformat()
    note.meta = {**(note.meta or {}), "sourceWatermark": wm}   # a new dict: the ORM records the change


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
    # B-04: ELIGIBILITY before the LIMIT - a live lease or a backing-off job must not hide later ready jobs
    rows = (await session.execute(
        select(TechniqueSourceJob).where(
            TechniqueSourceJob.outcome.in_(("in_progress", "retryable")),
            or_(TechniqueSourceJob.lease_until.is_(None), TechniqueSourceJob.lease_until <= now,
                TechniqueSourceJob.lease_owner.is_(None)),
            or_(TechniqueSourceJob.next_due_at.is_(None), TechniqueSourceJob.next_due_at <= now))
        .order_by(TechniqueSourceJob.created_at.asc()).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    out = []
    for j in rows:
        j.fence_token = int(j.fence_token or 0) + 1
        j.lease_owner = owner
        j.lease_until = now + dt.timedelta(seconds=lease_seconds)
        j.attempts = int(j.attempts or 0) + 1
        j.outcome = "in_progress"
        j.updated_at = now
        out.append(job_dict(j))
    await session.flush()
    return out


async def job_for_note(session, note_id: str) -> TechniqueSourceJob | None:
    """The CURRENT revision's job for a note (locked), or None when the note has no revision yet."""
    cur = await current_revision(session, note_id)
    if cur is None:
        return None
    return (await session.execute(select(TechniqueSourceJob).where(TechniqueSourceJob.revision_id == cur.id)
                                  .with_for_update())).scalars().first()


async def claim_for_note(session, note_id: str, *, owner: str, now: dt.datetime | None = None,
                         lease_seconds: int = DEFAULT_LEASE_SECONDS, retry: bool = False) -> dict | None:
    """Lease the current revision's job for `owner` under a NEW fence token (the worker path: `pending()`
    hands the lease to the transcription worker; the extraction / board / failure paths claim inline).
    None when another owner holds a live lease, or when the job is finished and `retry` is not set (a human
    retry re-opens a done/permanent job). Staged in the caller's session."""
    now = now or utcnow()
    job = await job_for_note(session, note_id)
    if job is None:
        return None
    if job.lease_owner and job.lease_until is not None and job.lease_until > now and job.lease_owner != owner:
        return None
    if job.outcome in ("done", "permanent") and not retry:
        return None
    if job.lease_owner == owner and job.lease_until is not None and job.lease_until > now and job.outcome == "in_progress":
        job.lease_until = now + dt.timedelta(seconds=lease_seconds)      # the same owner RENEWS: its fence stays valid
        job.updated_at = now
        await session.flush()
        return job_dict(job)
    job.fence_token = int(job.fence_token or 0) + 1
    job.lease_owner = owner
    job.lease_until = now + dt.timedelta(seconds=lease_seconds)
    job.attempts = int(job.attempts or 0) + 1
    job.outcome = "in_progress"
    job.next_due_at = None
    job.updated_at = now
    await session.flush()
    return job_dict(job)


async def sweep_expired(session, *, now: dt.datetime | None = None, limit: int = 200) -> int:
    """Release EXPIRED leases (a crashed or stalled worker) so the next claim can take the job at its
    recorded stage - under a NEW fence, so the stalled worker's late checkpoint is refused. Claims nothing
    itself: a delivery or an API call must never become a phantom owner of work it will not do."""
    now = now or utcnow()
    rows = (await session.execute(
        select(TechniqueSourceJob).where(TechniqueSourceJob.outcome == "in_progress",
                                         TechniqueSourceJob.lease_owner.is_not(None),
                                         TechniqueSourceJob.lease_until <= now)
        .limit(limit).with_for_update(skip_locked=True))).scalars().all()
    for j in rows:
        j.fence_token = int(j.fence_token or 0) + 1
        j.lease_owner = None
        j.lease_until = None
        j.updated_at = now
    await session.flush()
    return len(rows)


async def checkpoint(session, *, job_id: str, fence_token: int, item_key: str, artifact: dict | None = None,
                     stage: str | None = None, outcome: str | None = None, error: str | None = None,
                     now: dt.datetime | None = None, next_due_at: dt.datetime | None = None,
                     release: bool = False) -> dict:
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
    # B-04: a matching token is not enough - the job must be CLAIMED, in progress and its lease unexpired
    if job.outcome != "in_progress" or not job.lease_owner or job.lease_until is None or job.lease_until <= now:
        raise FenceMismatch(f"job {job_id[:8]}: no valid lease (outcome {job.outcome}, owner {job.lease_owner!r}, "
                            f"lease until {job.lease_until}) - an expired or unclaimed worker cannot checkpoint; nothing written")
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
        if outcome in ("done", "permanent", "retryable"):
            job.lease_owner = None                      # retryable = released for the next claim (after next_due_at)
            job.lease_until = None
        if outcome == "retryable":
            job.next_due_at = next_due_at
    if release and job.outcome == "in_progress":
        job.lease_owner = None                          # this stage's owner is done: the next stage claims anew
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
