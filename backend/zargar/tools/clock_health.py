"""Host clock health, measured against INDEPENDENT time sources (`clock-health-v1`, 2026-09-21).

Why this exists: on 2026-09-21 every EnhancedMarket experimental entry was refused by the first-sale
admission gate with `venue_time_in_future`. The venue timestamps were correct; the HOST clock was
behind, so every real quote looked future-dated. Reading the same host clock twice cannot detect
that - the comparison has to come from a machine that keeps its own time.

What it measures:
  * host vs NTP: the authoritative offset, with the round-trip uncertainty stated, from several
    independent servers. A quorum that agrees is what makes the number trustworthy.
  * host vs the database: cheap, always available, and useful as a continuous in-session signal -
    but the database clock is only another computer's opinion, so it is reported as corroboration,
    never as the authority.
  * the platform's own synchronization state (on Windows, the w32time service), because an offset
    that will come back after the next reboot is a different problem from a one-off step.

What it does NOT do: it never sets a clock, never changes a service, and never feeds a trading
decision. Repairing a clock is a host-administration act with a named owner; this tool's whole job
is to make the fault explicit and attributable so that no gate has to be weakened to hide it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import struct
import subprocess
import sys
import time

VERSION = "clock-health-v1"
NTP_EPOCH_DELTA = 2_208_988_800          # seconds between the NTP epoch (1900) and the Unix epoch (1970)
DEFAULT_SERVERS = ("time.windows.com", "time.google.com", "time.cloudflare.com", "pool.ntp.org", "time.nist.gov")
# How far the host may drift before the desk calls it a fault. The admission gate tolerates 1000 ms of
# apparent future, so half of that is the point where a correct venue timestamp starts being refused.
WARN_MS = 500
FAIL_MS = 1_000


def ntp_offset(host: str, timeout: float = 3.0) -> dict:
    """One NTP exchange. Returns the host's offset from that server in ms, with its uncertainty.

    offset = ((t2 - t1) + (t3 - t4)) / 2, delay = (t4 - t1) - (t3 - t2), where t1/t4 are read from the
    host clock and t2/t3 from the server's. A POSITIVE offset means the host is BEHIND the server.
    The offset is only as good as the round trip is symmetric, so delay/2 is carried as uncertainty
    rather than dropped.
    """
    pkt = bytearray(48)
    pkt[0] = 0x1B                                    # LI = 0, VN = 3, Mode = 3 (client)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t1 = time.time()
        s.sendto(bytes(pkt), (host, 123))
        data, _ = s.recvfrom(48)
        t4 = time.time()
    finally:
        s.close()
    if len(data) < 48:
        raise ValueError(f"short NTP reply ({len(data)} bytes)")
    f = struct.unpack("!12I", data[:48])
    t2 = f[8] + f[9] / 2**32 - NTP_EPOCH_DELTA        # server receive
    t3 = f[10] + f[11] / 2**32 - NTP_EPOCH_DELTA      # server transmit
    stratum = (f[0] >> 16) & 0xFF
    if stratum == 0 or t2 <= 0 or t3 <= 0:
        raise ValueError(f"unusable NTP reply (stratum {stratum})")   # kiss-of-death or empty
    delay = (t4 - t1) - (t3 - t2)
    return {"server": host, "offsetMs": round(((t2 - t1) + (t3 - t4)) / 2 * 1000, 1),
            "roundTripMs": round(delay * 1000, 1), "uncertaintyMs": round(abs(delay) / 2 * 1000, 1),
            "stratum": stratum}


def measure_ntp(servers=DEFAULT_SERVERS, *, timeout: float = 3.0) -> dict:
    """Ask several independent servers and take the MEDIAN. One server can be wrong or hijacked; a
    quorum that agrees to within a few milliseconds cannot all be wrong in the same direction."""
    rows, errors = [], []
    for h in servers:
        try:
            rows.append(ntp_offset(h, timeout))
        except Exception as e:                                        # noqa: BLE001
            errors.append({"server": h, "error": f"{type(e).__name__}: {e}"})
    if not rows:
        return {"status": "unknown", "why": "no NTP server answered - offline, or UDP 123 is blocked",
                "servers": [], "errors": errors, "offsetMs": None}
    offs = sorted(r["offsetMs"] for r in rows)
    median = offs[len(offs) // 2]
    spread = round(max(offs) - min(offs), 1)
    worst = max(r["uncertaintyMs"] for r in rows)
    # agreement matters as much as the number: a wide spread means the measurement itself is doubtful
    agreed = spread <= max(250.0, worst * 4)
    status = ("unknown" if not agreed else
              "fail" if abs(median) >= FAIL_MS else
              "warn" if abs(median) >= WARN_MS else "ok")
    return {"status": status, "offsetMs": median, "direction": ("host behind true time" if median > 0 else
                                                                "host ahead of true time" if median < 0 else "aligned"),
            "spreadMs": spread, "worstUncertaintyMs": worst, "agreed": agreed,
            "servers": rows, "errors": errors,
            "why": (None if agreed else "the servers disagree by more than the round trip explains - measurement not trusted")}


async def measure_db(database_url: str | None = None) -> dict:
    """The database's clock minus the host's, over one round trip. Corroboration, not authority: it
    says the two machines disagree, never which of them is right."""
    try:
        import asyncpg                                              # noqa: PLC0415
        from ..config import AppConfig                              # noqa: PLC0415
        url = (database_url or AppConfig().database_url).replace("postgresql+asyncpg://", "postgresql://")
        c = await asyncpg.connect(url)
        try:
            await c.execute("set default_transaction_read_only = on")
            t1 = time.time() * 1000
            db_ms = float(await c.fetchval("select extract(epoch from clock_timestamp()) * 1000"))
            t4 = time.time() * 1000
        finally:
            await c.close()
        mid = (t1 + t4) / 2
        return {"status": "ok", "offsetMs": round(db_ms - mid, 1), "roundTripMs": round(t4 - t1, 1),
                "note": "database clock minus host clock; corroborates NTP, never replaces it"}
    except Exception as e:                                          # noqa: BLE001
        return {"status": "unknown", "error": f"{type(e).__name__}: {e}", "offsetMs": None}


def platform_sync() -> dict:
    """Is the host configured to KEEP its clock right? An offset that returns after every reboot is a
    different fault from a single step, and only this answers which one it is."""
    if not sys.platform.startswith("win"):
        return {"platform": sys.platform, "status": "unknown", "note": "no check implemented for this platform"}
    out: dict = {"platform": "windows", "service": None, "startType": None, "status": "unknown"}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$s = Get-Service w32time; ConvertTo-Json @{Status=$s.Status.ToString(); StartType=$s.StartType.ToString()}"],
                           capture_output=True, text=True, timeout=25)
        d = json.loads(r.stdout.strip() or "{}")
        out["service"], out["startType"] = d.get("Status"), d.get("StartType")
        running = str(out["service"]).lower() == "running"
        persistent = str(out["startType"]).lower() in ("automatic", "automaticdelayedstart")
        out["status"] = "ok" if (running and persistent) else "fail"
        out["why"] = (None if out["status"] == "ok" else
                      f"time service is {out['service']} with start type {out['startType']}: "
                      "the clock is not being kept synchronized and any correction will drift again")
    except Exception as e:                                          # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


async def build(*, servers=DEFAULT_SERVERS, with_db: bool = True, database_url: str | None = None) -> dict:
    ntp = measure_ntp(servers)
    db = await measure_db(database_url) if with_db else {"status": "skipped", "offsetMs": None}
    plat = platform_sync()
    # The verdict follows the authoritative measurement. A stopped time service is a fault on its own
    # even while the clock happens to be right, because it says the drift will come back.
    status = ntp["status"]
    if status == "unknown" and db.get("offsetMs") is not None and abs(db["offsetMs"]) >= FAIL_MS:
        status = "suspect"                       # NTP unavailable, but the database says the two clocks disagree badly
    if plat.get("status") == "fail" and status == "ok":
        status = "warn"
    admission = None
    if ntp.get("offsetMs") is not None:
        # The gate refuses evidence more than 1000 ms in the future. When the host runs BEHIND, a correct
        # venue timestamp looks that far ahead, and every fresh quote is refused.
        admission = {"gateFutureToleranceMs": 1000,
                     "apparentFutureOnFreshQuoteMs": round(max(0.0, ntp["offsetMs"]), 1),
                     "breaksAdmission": ntp["offsetMs"] > 1000,
                     "note": "a host running behind makes correct venue timestamps look future-dated; "
                             "the gate is right to refuse them and must not be loosened to compensate"}
    return {"version": VERSION, "at": int(time.time() * 1000), "status": status,
            "ntp": ntp, "database": db, "platformSync": plat, "admissionImpact": admission,
            "thresholds": {"warnMs": WARN_MS, "failMs": FAIL_MS}}


def render(d: dict) -> str:
    n, db, p = d.get("ntp") or {}, d.get("database") or {}, d.get("platformSync") or {}
    L = [f"clock health: **{d['status']}** ({d['version']})", ""]
    if n.get("offsetMs") is not None:
        L.append(f"- host vs NTP: {n['offsetMs']:+.1f} ms ({n['direction']}), "
                 f"{len(n.get('servers') or [])} server(s) agreeing within {n['spreadMs']:.1f} ms, "
                 f"uncertainty at most {n['worstUncertaintyMs']:.1f} ms")
    else:
        L.append(f"- host vs NTP: unknown ({n.get('why') or 'not measured'})")
    L.append(f"- host vs database: {db['offsetMs']:+.1f} ms" if db.get("offsetMs") is not None
             else f"- host vs database: unknown ({db.get('error') or db.get('status')})")
    L.append(f"- time service: {p.get('service')} / start {p.get('startType')} -> {p.get('status')}"
             + (f"; {p['why']}" if p.get("why") else ""))
    a = d.get("admissionImpact")
    if a:
        L.append(f"- admission: a fresh venue quote reads {a['apparentFutureOnFreshQuoteMs']:.0f} ms in the future "
                 f"against a {a['gateFutureToleranceMs']} ms tolerance -> "
                 + ("**entries will be refused**" if a["breaksAdmission"] else "within tolerance"))
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="measure host clock health against independent sources (changes nothing)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-db", action="store_true", help="skip the database comparison")
    ap.add_argument("--server", action="append", help="NTP server (repeatable; defaults to five public servers)")
    a = ap.parse_args(argv)
    d = asyncio.run(build(servers=tuple(a.server) if a.server else DEFAULT_SERVERS, with_db=not a.no_db))
    print(json.dumps(d, indent=1, default=str) if a.json else render(d))
    return 0 if d["status"] in ("ok", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
