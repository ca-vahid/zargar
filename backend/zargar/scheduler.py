"""Engine-level scheduled jobs (EM team B4 / techniques research, 2026-08-27).

Techniques and engine services register named once-a-day jobs by ET wall-clock
time; the scheduler runs them, journals every run, and raises the same loud
alert path as the feed self-test when one fails. Registration:

    engine.scheduler.register("chain_snapshots", "16:30", fn)      # engine service
    engine.scheduler.register("tip_nightly_scan", "20:00", scan)   # a technique's scan

Semantics: a job runs once per ET calendar day, at the first loop tick at/after
its time (a restart after the time still runs it that evening — a missed nightly
scan is worse than a late one). Weekend runs are skipped unless
`weekdays_only=False`. Job failures never kill the scheduler.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from . import bus as topics

ET = ZoneInfo("America/New_York")
log = logging.getLogger("zargar.scheduler")

SCHEDULED_JOB_RAN = "ScheduledJobRan"
SCHEDULED_JOB_FAILED = "ScheduledJobFailed"


@dataclass
class _Job:
    name: str
    at: str                                   # "HH:MM" ET
    fn: Callable[[], Awaitable[Any]]
    weekdays_only: bool = True
    last_day: str = ""                        # ET date it last ran
    runs: int = 0
    failures: int = 0
    last_result: Any = field(default=None, repr=False)


class Scheduler:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._jobs: dict[str, _Job] = {}
        self._task: asyncio.Task | None = None

    def register(self, name: str, at_et: str, fn: Callable[[], Awaitable[Any]], *,
                 weekdays_only: bool = True) -> None:
        hh, mm = at_et.split(":")
        assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60, at_et
        self._jobs[name] = _Job(name=name, at=at_et, fn=fn, weekdays_only=weekdays_only)
        log.info("scheduled job registered: %s at %s ET", name, at_et)

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)

    def status(self) -> list[dict]:
        return [{"name": j.name, "at": j.at, "weekdaysOnly": j.weekdays_only, "lastDay": j.last_day,
                 "runs": j.runs, "failures": j.failures} for j in self._jobs.values()]

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(30)

    async def _tick(self) -> None:
        now = dt.datetime.now(ET)
        day = now.strftime("%Y-%m-%d")
        minutes = now.hour * 60 + now.minute
        for job in list(self._jobs.values()):
            if job.last_day == day:
                continue
            if job.weekdays_only and now.weekday() >= 5:
                continue
            hh, mm = (int(x) for x in job.at.split(":"))
            if minutes < hh * 60 + mm:
                continue
            job.last_day = day
            await self._run(job, day)

    async def _run(self, job: _Job, day: str) -> None:
        t0 = dt.datetime.now(dt.timezone.utc)
        try:
            result = await job.fn()
            job.runs += 1
            job.last_result = result
            secs = (dt.datetime.now(dt.timezone.utc) - t0).total_seconds()
            log.info("scheduled job %s ran (%.1fs)", job.name, secs)
            try:
                await self.engine.journal.append(SCHEDULED_JOB_RAN, {
                    "job": job.name, "date": day, "seconds": round(secs, 1),
                    "result": result if isinstance(result, (int, float, str, bool, dict, list)) else None})
            except Exception:
                log.exception("journaling scheduled job failed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            job.failures += 1
            msg = f"scheduled job {job.name} FAILED: {exc}"
            log.exception(msg)
            try:
                await self.engine.journal.append(SCHEDULED_JOB_FAILED, {
                    "job": job.name, "date": day, "error": str(exc)})
            except Exception:
                pass
            self.engine.bus.publish(topics.TECHNIQUE, {"kind": "alert", "level": "warning", "text": msg})
