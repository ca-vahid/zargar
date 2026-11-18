"""Questions for the user (2026-11-18): Claude asks, the phone shows it with its answer buttons, the answer is
stored for the asker. An answer is words on the record - it never arms, approves or moves anything by itself.

NOTE: no `from __future__ import annotations` - see api/app.py.
"""
from typing import Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

from ..questions import QuestionService


class QuestionSpec(BaseModel):
    text: str
    detail: Optional[str] = None
    options: Optional[list[str]] = None
    askedBy: Optional[str] = None
    url: Optional[str] = None
    expiresAt: Optional[str] = None


class AnswerBody(BaseModel):
    answer: str


def build_question_routes(app, eng, auth, config) -> None:
    svc = QuestionService(eng)

    @app.get("/api/questions", dependencies=[auth])
    async def questions_list(open_only: bool = False, limit: int = 50):
        return await svc.list(open_only=open_only, limit=limit)

    @app.post("/api/questions", dependencies=[auth])
    async def questions_ask(body: QuestionSpec):
        try:
            return await svc.ask(body.text, detail=body.detail, options=body.options, asked_by=body.askedBy or "claude",
                                 url=body.url, expires_at=body.expiresAt)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/questions/{qid}", dependencies=[auth])
    async def questions_get(qid: str):
        q = await svc.get(qid)
        if q is None:
            raise HTTPException(status_code=404, detail="no such question")
        return q

    @app.post("/api/questions/{qid}/answer", dependencies=[auth])
    async def questions_answer(qid: str, body: AnswerBody, request: Request):
        via = "phone" if (request.headers.get("x-zargar-client") or "").lower() == "phone" else "app"
        try:
            return await svc.answer(qid, body.answer, via=via)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/questions/{qid}/cancel", dependencies=[auth])
    async def questions_cancel(qid: str):
        try:
            return await svc.cancel(qid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
