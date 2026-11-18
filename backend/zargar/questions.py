"""Questions for the user (2026-11-18). When Claude (or a desk job) needs a decision only the user can make - "the
corrected plan needs your arm", "no USD at Webull: convert or skip?" - it asks HERE instead of only in a chat window
the user may not be watching: the question is stored, pushed to the phone, shown at the top of the phone's Home
with its answer buttons, and the answer is stored for the asker to read. A question changes nothing by itself: the
answer is words on the record, and whoever asked acts on it under their own rules (an answer never arms an order,
flips a gate or moves money by itself).

Lifecycle: open -> answered | cancelled | expired (expiry is judged at read time; no sweep).
"""
from __future__ import annotations

import contextlib
import datetime as dt

from sqlalchemy import select

from . import events as ev
from .domain import new_id
from .models import DeskQuestion, utcnow

MAX_OPTIONS = 4
MAX_TEXT = 300


class QuestionService:
    def __init__(self, engine) -> None:
        self.engine = engine

    async def ask(self, text: str, *, detail: str | None = None, options: list[str] | None = None,
                  asked_by: str = "claude", url: str | None = None, expires_at: str | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("a question needs its text")
        if len(text) > MAX_TEXT:
            raise ValueError(f"keep the question under {MAX_TEXT} characters; put the rest in detail")
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        if len(opts) > MAX_OPTIONS:
            raise ValueError(f"at most {MAX_OPTIONS} answer options")
        if len(set(o.lower() for o in opts)) != len(opts):
            raise ValueError("answer options must differ")
        expires = None
        if expires_at:
            expires = dt.datetime.fromisoformat(str(expires_at))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.timezone.utc)
            if expires <= utcnow():
                raise ValueError("the expiry must be in the future")
        row = DeskQuestion(id=new_id(), text=text, detail=(detail or "").strip() or None, options=opts,
                           asked_by=(asked_by or "claude")[:40], url=(url or None), expires_at=expires, status="open")
        async with self.engine.sf() as session:
            session.add(row)
            await session.commit()
        await self._journal(row, "asked")
        push = getattr(self.engine, "push", None)
        if push is not None:
            with contextlib.suppress(Exception):
                await push.send("Zargar needs your answer", text, url="/questions", tag=f"question-{row.id[:8]}",
                                level="warning", channel="approvals")
        return self.to_dict(row)

    async def list(self, *, open_only: bool = False, limit: int = 50) -> list[dict]:
        async with self.engine.sf() as session:
            q = select(DeskQuestion).order_by(DeskQuestion.created_at.desc()).limit(max(1, min(int(limit), 200)))
            rows = (await session.execute(q)).scalars().all()
        out = [self.to_dict(r) for r in rows]
        return [d for d in out if d["status"] == "open"] if open_only else out

    async def get(self, qid: str) -> dict | None:
        async with self.engine.sf() as session:
            row = await session.get(DeskQuestion, qid)
        return self.to_dict(row) if row else None

    async def answer(self, qid: str, answer: str, *, via: str = "app") -> dict:
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("an answer needs its text")
        async with self.engine.sf() as session:
            row = await session.get(DeskQuestion, qid)
            if row is None:
                raise ValueError("no such question")
            if self._status(row) != "open":
                raise ValueError(f"this question is {self._status(row)}")
            row.status, row.answer, row.answered_at, row.answered_via = "answered", answer[:1000], utcnow(), via[:20]
            await session.commit()
        await self._journal(row, "answered")
        return self.to_dict(row)

    async def cancel(self, qid: str) -> dict:
        async with self.engine.sf() as session:
            row = await session.get(DeskQuestion, qid)
            if row is None:
                raise ValueError("no such question")
            if row.status == "open":
                row.status = "cancelled"
                await session.commit()
                await self._journal(row, "cancelled")
        return self.to_dict(row)

    @staticmethod
    def _status(r: DeskQuestion) -> str:
        if r.status == "open" and r.expires_at is not None and r.expires_at <= utcnow():
            return "expired"
        return r.status

    async def _journal(self, row: DeskQuestion, stage: str) -> None:
        with contextlib.suppress(Exception):
            await self.engine.journal.append(ev.DESK_QUESTION, {
                "id": row.id, "stage": stage, "text": row.text, "askedBy": row.asked_by, "answer": row.answer,
                "via": row.answered_via}, aggregate_type="desk_question", aggregate_id=row.id)

    @classmethod
    def to_dict(cls, r: DeskQuestion) -> dict:
        return {"id": r.id, "text": r.text, "detail": r.detail, "options": list(r.options or []),
                "status": cls._status(r), "askedBy": r.asked_by, "url": r.url, "answer": r.answer,
                "answeredVia": r.answered_via,
                "answeredAt": r.answered_at.isoformat() if r.answered_at else None,
                "expiresAt": r.expires_at.isoformat() if r.expires_at else None,
                "createdAt": r.created_at.isoformat() if r.created_at else None}
