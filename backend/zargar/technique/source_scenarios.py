"""EM source scenarios (`source-scenarios-v1`, 2026-09-18; integrated plan workstream A).

What an author ACTUALLY said, as a structured, revision-bound, append-only artifact (`technique_source_artifacts`,
kind `scenarios`) - and a matcher that refuses to call a ticker-only coincidence "aligned".

Deterministic: zero model calls. The input is the immutable source revision (verbatim text), the transcript artifact
(speech, `[m:ss]` stamps) and the persisted extraction artifact (the model's flat board lines). This module does NOT
trust the extraction: every board line is re-checked against the verbatim evidence, and what cannot be verified stays
unresolved / conflicting and is HELD - never turned into a trade candidate.

  author-supplied   symbol as spoken/written, direction words, condition text, levels, option mentions, horizon words
  app-derived       resolved ticker, numeric level, setup family, pairing, usable time, expiry - each with `derivation`

Frozen rules:
  * usableAt = the latest completion time of every input the scenario needed (revision receipt, transcript, extraction).
    A retrospective correction is usable at ITS OWN time - it never changes what the app could have known live.
  * an ambiguous or unverifiable ticker is `unresolved`; an extracted ticker whose evidence span names a DIFFERENT
    ticker is `conflict` (MU spoken, TSLA extracted). Neither is tradable.
  * a call/put strike ("700C") is an option mention, never an underlying target. A level wildly inconsistent with the
    strikes beside it ("1155" with 160C/165C) is `level_conflict` - flagged, never auto-corrected.
  * "break up or reject down" = two branches sharing a `pairId`.
  * nothing here arms, sizes or orders. Candidates built from scenarios carry origin `scenario:<id>` (order-free).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

VERSION = "source-scenarios-v1"
MATCHER_VERSION = "source-plan-match-v1"
REGION_TOLERANCE_PCT = 0.5          # a plan trigger within 0.5% of the stated level is "the same region" (app convention)

# company / spoken aliases for the names the room actually says. A ticker NOT verifiable from the evidence is unresolved.
ALIASES = {
    "AAPL": ["apple"], "AMZN": ["amazon"], "AMD": ["amd", "a m d"], "APP": ["applovin", "app loving", "app lovin"], "ARM": ["arm"],
    "AVGO": ["broadcom", "avgo"], "COIN": ["coinbase"], "GOOGL": ["google", "alphabet"], "INTC": ["intel"], "IWM": ["iwm", "i w m", "russell"],
    "META": ["meta", "facebook"], "MRNA": ["moderna"], "MSFT": ["microsoft"], "MU": ["micron", "m you", "m u"], "NFLX": ["netflix"],
    "NVDA": ["nvidia", "in video"], "ORCL": ["oracle"], "PLTR": ["palantir"], "QQQ": ["qqq", "the q's", "cues", "q q q"], "SPCX": ["space x", "spacex"],
    "SPY": ["spy"], "SPX": ["spx", "s p x"], "TSLA": ["tesla"], "SBUX": ["starbucks"], "PANW": ["palo alto"], "FSLR": ["first solar"],
}
_LETTER = {"a": "a|ay", "b": "b|be|bee", "c": "c|see|sea", "d": "d|dee", "e": "e", "f": "f|ef", "g": "g|gee", "h": "h", "i": "i|eye", "j": "j|jay",
           "k": "k|kay", "l": "l|el", "m": "m|em", "n": "n|en", "o": "o|oh", "p": "p|pee", "q": "q|cue", "r": "r|are", "s": "s|es", "t": "t|tee",
           "u": "u|you", "v": "v|vee", "w": "w", "x": "x|ex", "y": "y|why", "z": "z|zee"}
_STAMP = re.compile(r"\[(\d+):(\d{2})(?::(\d{2}))?\]")
_OPT = re.compile(r"(?<![\w.])(\d{1,5}(?:\.\d+)?)\s?([CP])(?![a-zA-Z])", re.I)
_NUM = re.compile(r"(?<![\w.])(\d{1,5}(?:[.,]\d+)?)(?![\w%])")
_SPEECH_DEC = re.compile(r"(?<![\d.])(\d{2,4}) (\d{2})(?!\d)")


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).isoformat()
    return str(v)


def _ts(v) -> dt.datetime | None:
    if v is None or isinstance(v, dt.datetime):
        return v if (v is None or v.tzinfo) else v.replace(tzinfo=dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T", 1))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------ parsing
def parse_board_line(line: str) -> dict:
    """`SYM | long | trigger: ... | target: ... | note: ...` (the extraction's flat board row). Tolerant: unknown
    segments are kept in `other`."""
    parts = [p.strip() for p in str(line or "").split("|")]
    out = {"raw": line, "symbol": (parts[0].upper().lstrip("$") if parts else ""), "direction": None, "trigger": None, "targets": [], "note": None, "other": []}
    for p in parts[1:]:
        low = p.lower()
        if low in ("long", "short", "both", "neutral", "watch", "avoid"):
            out["direction"] = low
        elif low.startswith("trigger:"):
            out["trigger"] = p.split(":", 1)[1].strip()
        elif low.startswith("target:"):
            out["targets"].append(p.split(":", 1)[1].strip())
        elif low.startswith("note:"):
            out["note"] = p.split(":", 1)[1].strip()
        elif p:
            out["other"].append(p)
    return out


def speech_numbers(text: str) -> str:
    """Speech-to-text writes 551.42 as `551 42`. Joined ONLY for the `ddd dd` shape; derivation `speech-decimal-join-v1`."""
    return _SPEECH_DEC.sub(lambda m: f"{m.group(1)}.{m.group(2)}", str(text or ""))


def option_mentions(text: str) -> list[dict]:
    return [{"strike": float(m.group(1)), "right": m.group(2).upper(), "raw": m.group(0).strip(), "start": m.start(), "end": m.end()}
            for m in _OPT.finditer(str(text or ""))]


def underlying_numbers(text: str) -> list[float]:
    """Numbers in the text that are NOT option strikes (a number immediately followed by C/P is a strike mention)."""
    t = str(text or "")
    strikes = {(m.start(1), m.end(1)) for m in _OPT.finditer(t)}
    out = []
    for m in _NUM.finditer(t):
        if (m.start(1), m.end(1)) in strikes:
            continue
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


def _mention_patterns(symbol: str) -> list[re.Pattern]:
    sym = symbol.lower()
    pats = [re.compile(rf"(?<![a-z0-9])\$?{re.escape(sym)}(?![a-z0-9])", re.I)]
    if 2 <= len(sym) <= 4 and sym.isalpha():
        spoken = r"[\s.\-]+".join(f"(?:{_LETTER[ch]})" for ch in sym)
        pats.append(re.compile(rf"(?<![a-z0-9]){spoken}(?![a-z0-9])", re.I))
    for a in ALIASES.get(symbol.upper(), []):
        pats.append(re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", re.I))
    return pats


def symbol_mentions(text: str, symbols) -> list[dict]:
    """Every place a known ticker is named in the evidence (ticker token, spelled letters, company alias), in order."""
    t = str(text or "")
    out = []
    for s in sorted({str(x).upper() for x in symbols or [] if x}):
        for p in _mention_patterns(s):
            for m in p.finditer(t):
                out.append({"symbol": s, "start": m.start(), "end": m.end(), "text": m.group(0)})
    out.sort(key=lambda r: (r["start"], -(r["end"] - r["start"])))
    dedup, last_end = [], -1
    for r in out:
        if r["start"] >= last_end:
            dedup.append(r); last_end = r["end"]
    return dedup


def _segments(text: str, kind: str) -> list[dict]:
    """Evidence segments: transcript lines keyed by their `[m:ss]` stamp, or the text's own lines."""
    t = str(text or "")
    segs, pos = [], 0
    for line in t.split("\n"):
        start = pos; pos += len(line) + 1
        if not line.strip():
            continue
        m = _STAMP.match(line.strip()) if kind == "transcript" else None
        off = (int(m.group(1)) * 60 + int(m.group(2))) if m and not m.group(3) else ((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else None)
        segs.append({"start": start, "end": start + len(line), "text": line, "offsetSeconds": off})
    return segs


_STOP = {"this", "that", "with", "here", "from", "have", "will", "would", "there", "their", "about", "which", "could", "also", "just", "into", "than", "then", "them",
         "target", "trigger", "note", "continuation", "setup", "watch", "looks", "good", "really", "right", "still", "long", "short"}


def _tokens(s: str) -> set[str]:
    s = speech_numbers(s).lower()
    return {w for w in re.findall(r"[a-z]{4,}|\d+(?:\.\d+)?", s) if w not in _STOP}


def locate_evidence(line: dict, source_text: str, kind: str, all_symbols) -> dict:
    """Find the span of the source that carries this board line, and which ticker THAT span names.
    text post: the source line that names the symbol verbatim (and, when several do, the one sharing the most words).
    transcript: the 3-line window with the best word/number overlap with the line's trigger+targets+note, then the
    nearest ticker mention at or before the window's end (looking back at most 4 lines)."""
    sym = line.get("symbol") or ""
    segs = _segments(source_text, kind)
    if not segs:
        return {"located": False, "why": "no_source_text", "spans": [], "evidenceSymbol": None, "symbolSeen": False}
    want = _tokens(" ".join(filter(None, [line.get("trigger"), " ".join(line.get("targets") or []), line.get("note")])))
    mentions = symbol_mentions(source_text, set(all_symbols or []) | {sym} | set(ALIASES))
    seen = any(m["symbol"] == sym for m in mentions)
    if kind != "transcript":
        cands = [s for s in segs if any(m["symbol"] == sym and s["start"] <= m["start"] < s["end"] for m in mentions)]
        if not cands:
            return {"located": False, "why": "symbol_not_in_source_text", "spans": [], "evidenceSymbol": None, "symbolSeen": False}
        want_dir = line.get("direction")
        def score(s):
            sc = len(want & _tokens(s["text"]))
            return sc
        best = max(cands, key=score)
        # several lines for one symbol (SPX above / SPX fails): prefer the one whose words overlap most; ties keep order
        return {"located": True, "spans": [_span(best, kind)], "evidenceSymbol": sym, "symbolSeen": True, "score": score(best), "wantDirection": want_dir}
    # topic per transcript line: the LAST ticker named in the line, else the previous line's topic (a speaker stays on
    # a chart until he names the next one). A ticker's ZONE = the lines whose topic it is.
    topics, cur = [], None
    for sg in segs:
        ms = [m for m in mentions if sg["start"] <= m["start"] < sg["end"]]
        if ms:
            cur = ms[-1]["symbol"]
        topics.append(cur)
    named_in = [{m["symbol"] for m in mentions if sg["start"] <= m["start"] < sg["end"]} for sg in segs]

    def best_window(allowed):
        bi, bs = None, 0
        for i in range(len(segs)):
            idx = [k for k in range(i, min(i + 3, len(segs))) if allowed(k)]
            if not idx or idx[0] != i:
                continue
            sc = len(want & _tokens(" ".join(segs[k]["text"] for k in idx)))
            if sc > bs:
                bi, bs = i, sc
        return bi, bs
    own_i, own_sc = best_window(lambda k: topics[k] == sym or sym in named_in[k])
    glob_i, glob_sc = best_window(lambda k: True)
    if own_i is not None and own_sc >= 2:
        win = [segs[k] for k in range(own_i, min(own_i + 3, len(segs))) if topics[k] == sym or sym in named_in[k]]
        return {"located": True, "spans": [_span(x, kind) for x in win], "evidenceSymbol": sym, "symbolSeen": True, "score": own_sc}
    if glob_i is None or glob_sc < 3:
        return {"located": False, "why": "no_matching_passage", "spans": [], "evidenceSymbol": None, "symbolSeen": seen}
    win = segs[glob_i:glob_i + 3]
    tps = [topics[k] for k in range(glob_i, min(glob_i + 3, len(segs))) if topics[k]]
    topic = max(set(tps), key=tps.count) if tps else None
    return {"located": True, "spans": [_span(x, kind) for x in win], "evidenceSymbol": topic, "symbolSeen": seen, "score": glob_sc}


def _span(seg: dict, kind: str) -> dict:
    return {"artifact": ("transcript" if kind == "transcript" else "revision_text"), "start": seg["start"], "end": seg["end"],
            "offsetSeconds": seg.get("offsetSeconds"), "quote": seg["text"].strip()[:240]}


# --------------------------------------------------------------------------------------------- derivations
def derive_family(direction: str, text: str) -> tuple[str | None, str]:
    """App-derived setup family from the author's condition words (derivation `family-words-v1`); None when unclear."""
    t = (text or "").lower()
    if direction == "long":
        if "wedge" in t:
            return "wedge_break", "family-words-v1:wedge"
        if re.search(r"back ?test|hold|support|bounce|must hold", t):
            return "bounce", "family-words-v1:hold/support"
        if re.search(r"break|through|above|push|reclaim|over|take the high", t):
            return "breakout", "family-words-v1:break/above"
    if direction == "short":
        if re.search(r"reject|fail(s|ed)? (at|to)|resistance holds", t):
            return "reject", "family-words-v1:reject"
        if re.search(r"below|fails|break|under|lose|drop", t):
            return "breakdown", "family-words-v1:below/fails"
    return None, "family-words-v1:unclear"


_MONTH_NUM = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(st|nd|rd|th)?\b", re.I)


def derive_level(trigger_text: str) -> tuple[float | None, str]:
    nums = underlying_numbers(speech_numbers(_MONTH_NUM.sub(" ", str(trigger_text or ""))))
    if len(nums) == 1:
        return nums[0], "first-number-in-condition-v1"
    if len(nums) > 1:
        return nums[0], "first-number-in-condition-v1:several_numbers"
    return None, "no_number_in_condition"


def derive_horizon(text: str) -> tuple[str | None, str]:
    t = (text or "").lower()
    if re.search(r"0 ?dte|0dt", t):
        return "0dte", "horizon-words-v1"
    if "swing" in t or re.search(r"\b\d{1,2}/\d{1,2}\b", t):
        return "swing", "horizon-words-v1"
    if "at the open" in t or "open" in t.split():
        return "open", "horizon-words-v1"
    return None, "horizon-words-v1:unstated"


def session_close_utc(usable: dt.datetime | None) -> str | None:
    """App convention `expiry-session-close-v1`: a same-day idea expires at 16:00 ET of the session it became usable in."""
    if usable is None:
        return None
    from zoneinfo import ZoneInfo
    et = usable.astimezone(ZoneInfo("America/New_York"))
    return et.replace(hour=16, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc).isoformat()


# ------------------------------------------------------------------------------------------------ the builder
def build_scenarios(source: dict, *, known_symbols=None) -> dict:
    """`source` = {note:{id,kind,messageId,channelId,channelName}, revision:{id,revision,kind,authorId,authorName,text,
    publishedAt,receivedAt,deleted}, transcript:{artifactId,text,completedAt}|None, extraction:{artifactId,payload,
    completedAt}|None}. `known_symbols` = the tradable universe (a ticker outside it is unresolved)."""
    note, rev = source.get("note") or {}, source.get("revision") or {}
    tr, ex = source.get("transcript") or None, source.get("extraction") or None
    payload = (ex or {}).get("payload") or {}
    is_video = bool(tr and tr.get("text"))
    ev_text = (tr or {}).get("text") if is_video else (rev.get("text") or "")
    ev_kind = "transcript" if is_video else "text"
    needed = [_ts(rev.get("receivedAt")), _ts((ex or {}).get("completedAt"))] + ([_ts(tr.get("completedAt"))] if is_video else [])
    usable = max(needed) if all(x is not None for x in needed) else None
    known = {str(s).upper() for s in (known_symbols or [])}
    lines = [parse_board_line(l) for l in (payload.get("board") or [])]
    all_syms = {l["symbol"] for l in lines if l["symbol"]} | {str(s).upper() for s in payload.get("symbols") or []}
    author = {"id": rev.get("authorId"), "displayName": rev.get("authorName") or note.get("author")}
    url = None
    if note.get("guildId") and note.get("channelId") and note.get("messageId"):
        url = f"https://discord.com/channels/{note['guildId']}/{note['channelId']}/{note['messageId']}"
    scenarios, flags_all = [], []
    for i, l in enumerate(lines):
        if rev.get("deleted"):
            break
        sym = l["symbol"]
        ev = locate_evidence(l, ev_text, ev_kind, all_syms)
        cond_text = " ".join(filter(None, [l.get("trigger"), l.get("note")]))
        span_text = " ".join(s["quote"] for s in ev.get("spans") or [])
        opts = option_mentions(span_text if ev_kind == "text" else "") or option_mentions(cond_text)
        flags = []
        # --- symbol resolution: verified against the evidence, never trusted from the model
        if not sym or not re.fullmatch(r"[A-Z.]{1,6}", sym):
            status, resolved = "unresolved", None; flags.append("symbol_not_a_ticker")
        elif known and sym not in known:
            status, resolved = "unresolved", None; flags.append("symbol_not_in_universe")
        elif not ev["located"]:
            status, resolved = "unresolved", None; flags.append("evidence_" + ev.get("why", "unlocated"))
        elif ev.get("evidenceSymbol") and ev["evidenceSymbol"] != sym and not (sym in known or sym in ALIASES or ev.get("symbolSeen")):
            status, resolved = "unresolved", None
            flags.append(f"symbol_never_named_in_source"); flags.append(f"passage_topic_hypothesis:{ev['evidenceSymbol']}")
        elif ev.get("evidenceSymbol") and ev["evidenceSymbol"] != sym:
            status, resolved = "conflict", None; flags.append(f"evidence_names_{ev['evidenceSymbol']}_not_{sym}")
        elif not ev.get("evidenceSymbol") and not ev.get("symbolSeen"):
            status, resolved = "unresolved", None; flags.append("symbol_never_named_in_source")
        elif not ev.get("evidenceSymbol"):
            status, resolved = "ambiguous", None; flags.append("passage_names_no_ticker")
        else:
            status, resolved = "resolved", sym
        # --- targets: underlying numbers only; a strike is an option mention
        strikes = {o["strike"] for o in opts}
        src_nums = set(underlying_numbers(speech_numbers(span_text))) if ev_kind == "text" else None
        tgts, dropped = [], []
        for tt in l.get("targets") or []:
            for n in underlying_numbers(speech_numbers(tt)):
                if src_nums is not None and n not in src_nums and n in strikes:
                    dropped.append(n); continue
                tgts.append(n)
        if dropped:
            flags.append("target_was_option_strike:" + ",".join(f"{x:g}" for x in dropped))
        level, level_der = derive_level(l.get("trigger") or "")
        if level and strikes:
            far = [k for k in strikes if k > 0 and (level / k > 3.0 or level / k < 1 / 3.0)]
            if far:
                flags.append(f"level_conflict:{level:g}_vs_strikes_" + "/".join(f"{k:g}" for k in sorted(far)))
        directions = ["long", "short"] if l.get("direction") == "both" else [l.get("direction")]
        pair = _h([note.get("id"), rev.get("id"), sym, i])[:16] if len(directions) > 1 else None
        for d in directions:
            fam, fam_der = derive_family(d or "", cond_text)
            hz, hz_der = derive_horizon(" ".join(filter(None, [cond_text, span_text])))
            held = [f for f in flags if f.startswith(("level_conflict", "evidence_", "symbol_", "passage_"))] or ([] if status == "resolved" else [status])
            sid = _h([VERSION, note.get("id"), rev.get("id"), sym, d, l.get("trigger"), i])[:24]
            scenarios.append({
                "scenarioId": sid, "pairId": pair, "branch": (d if pair else None), "index": i,
                "authorSupplied": {"symbolAsExtracted": sym, "direction": d, "condition": l.get("trigger"), "targetsText": list(l.get("targets") or []),
                                   "note": l.get("note"), "optionMentions": [{k: o[k] for k in ("strike", "right", "raw")} for o in opts],
                                   "stop": None, "stopNote": "the author stated no stop - unknown, never invented"},
                "symbol": {"status": status, "resolved": resolved, "evidenceSymbol": ev.get("evidenceSymbol"), "derivation": "evidence-verified-ticker-v1"},
                "appDerived": {"family": fam, "familyDerivation": fam_der, "level": level, "levelDerivation": level_der,
                               "underlyingTargets": tgts, "targetsDerivation": "numbers-not-strikes-v1", "horizon": hz, "horizonDerivation": hz_der,
                               "expiresAt": (session_close_utc(usable) if hz != "swing" else None),
                               "expiryDerivation": ("expiry-session-close-v1" if hz != "swing" else "swing: author horizon - no app expiry invented")},
                "stance": ("preferred" if re.search(r"favou?rite|love|like this a lot", (l.get("note") or "") + " " + span_text, re.I) else "normal"),
                "evidence": ev.get("spans") or [], "flags": flags,
                "disposition": ("held_for_resolution" if held else "candidate_source"), "heldReasons": held,
            })
        flags_all += flags
    avoid = []
    for v in payload.get("vetoes") or []:
        sym = re.split(r"[\s—\-:]", str(v).strip(), maxsplit=1)[0].upper()
        avoid.append({"symbol": sym, "text": v, "status": ("no_chase" if re.search(r"chase|extended|gapping up too", str(v), re.I) else "avoid")})
    body = {"version": VERSION, "note": {"id": note.get("id"), "kind": note.get("kind"), "channelName": note.get("channelName"), "messageId": note.get("messageId"), "messageUrl": url},
            "revision": {"id": rev.get("id"), "revision": rev.get("revision"), "kind": rev.get("kind"), "deleted": bool(rev.get("deleted"))},
            "author": author, "inputs": {"transcriptArtifactId": (tr or {}).get("artifactId"), "extractionArtifactId": (ex or {}).get("artifactId"), "evidenceKind": ev_kind},
            "times": {"sourcePostedAt": _iso(rev.get("publishedAt")), "receivedAt": _iso(rev.get("receivedAt")),
                      "transcribedAt": _iso((tr or {}).get("completedAt")), "extractedAt": _iso((ex or {}).get("completedAt")),
                      "usableAt": _iso(usable), "usableDerivation": "max(revision receipt, transcript, extraction) - never the message timestamp"},
            "scenarios": scenarios, "avoid": avoid, "authorResult": {"status": "unknown", "note": "no entry/exit ledger of the author exists in the material; platform P&L is not the author's result"}}
    body["inputHash"] = _h({"rev": rev.get("id"), "text": rev.get("text"), "transcript": (tr or {}).get("artifactId"), "extraction": (ex or {}).get("artifactId")})
    body["configHash"] = _h({"version": VERSION, "aliases": ALIASES, "tolerance": REGION_TOLERANCE_PCT})
    return body


def apply_corrections(payload: dict, corrections: list, *, corrected_at: str, corrected_by: str) -> dict:
    """A NEW artifact payload (append-only): each correction = {scenarioId|match:{symbolAsExtracted,index}, set:{...},
    evidence, reason}. The original payload is never edited; the corrected scenario is usable at `corrected_at`, so a
    retrospective fix cannot leak into what the app could have known live."""
    out = json.loads(json.dumps(payload, default=str))
    applied = []
    for c in corrections or []:
        for s in out["scenarios"]:
            m = c.get("match") or {}
            if (c.get("scenarioId") and s["scenarioId"] == c["scenarioId"]) or \
               (m and s["authorSupplied"]["symbolAsExtracted"] == m.get("symbolAsExtracted") and (m.get("index") is None or s["index"] == m.get("index"))):
                before = {"symbol": dict(s["symbol"]), "disposition": s["disposition"]}
                st = c.get("set") or {}
                if "resolvedSymbol" in st:
                    s["symbol"] = {**s["symbol"], "status": ("resolved" if st["resolvedSymbol"] else st.get("status", "unresolved")), "resolved": st["resolvedSymbol"],
                                   "derivation": "reviewed-correction-v1"}
                if st.get("status") and "resolvedSymbol" not in st:
                    s["symbol"]["status"] = st["status"]
                s["heldReasons"] = [] if s["symbol"]["status"] == "resolved" and not any(f.startswith("level_conflict") for f in s["flags"]) else (s["heldReasons"] or [s["symbol"]["status"]])
                s["disposition"] = "candidate_source" if not s["heldReasons"] else "held_for_resolution"
                s["correction"] = {"of": s["scenarioId"], "before": before, "reason": c.get("reason"), "evidence": c.get("evidence"),
                                   "correctedAt": corrected_at, "correctedBy": corrected_by, "usableAt": corrected_at}
                applied.append(s["scenarioId"])
    out["correctionOf"] = {"inputHash": payload.get("inputHash"), "configHash": payload.get("configHash"), "applied": applied,
                           "correctedAt": corrected_at, "correctedBy": corrected_by}
    out["configHash"] = _h({"base": payload.get("configHash"), "corrections": corrections, "at": corrected_at})
    return out


def usable_at(scenario: dict, payload: dict) -> str | None:
    return ((scenario.get("correction") or {}).get("usableAt")) or (payload.get("times") or {}).get("usableAt")


# ------------------------------------------------------------------------------------------------ the matcher
def match_plan(scenario: dict, payload: dict, plan: dict, *, plan_built_at: str | None = None, plan_origin: str | None = None) -> dict:
    """Compare ONE scenario branch with ONE saved plan - its FULL trigger set, never a representative row."""
    sym = (scenario.get("symbol") or {}).get("resolved")
    sup, app = scenario["authorSupplied"], scenario["appDerived"]
    rows = []
    for t in (plan or {}).get("triggers") or []:
        kind = str(t.get("kind") or "")
        t_dir = str(t.get("direction") or ("short" if kind in ("reject", "breakdown") else "long"))
        lvl = t.get("levelPrice") if t.get("levelPrice") is not None else t.get("entry")
        region = None
        if app.get("level") and lvl:
            region = abs(float(lvl) - float(app["level"])) / float(app["level"]) * 100.0
        same_dir = sup.get("direction") in ("long", "short") and t_dir == sup["direction"]
        same_region = region is not None and region <= REGION_TOLERANCE_PCT
        fam_ok = (app.get("family") is None) or kind == app["family"] or {kind, app["family"]} <= {"breakout", "wedge_break"}
        if not same_dir and same_region:
            verdict = "opposite_direction_same_level"
        elif same_dir and same_region and fam_ok:
            verdict = "aligned"
        elif same_dir and same_region:
            verdict = "same_level_different_family"
        elif same_dir and region is None:
            verdict = "same_direction_level_unknown"
        elif same_dir:
            verdict = "same_direction_different_region"
        else:
            verdict = "unrelated"
        rows.append({"trigger": t.get("id"), "kind": kind, "direction": t_dir, "level": lvl, "valid": t.get("valid"), "riskReward": t.get("riskReward"),
                     "regionDistancePct": (round(region, 3) if region is not None else None), "verdict": verdict,
                     "targetsVsSource": {"plan": [x.get("price") if isinstance(x, dict) else x for x in (t.get("targets") or [])], "source": app.get("underlyingTargets")}})
    ua, built = _ts(usable_at(scenario, payload)), _ts(plan_built_at)
    causal = None if (ua is None or built is None) else (built >= ua)
    aligned = [r for r in rows if r["verdict"] == "aligned"]
    best = next((r for r in aligned if r.get("valid")), None) or (aligned[0] if aligned else None)
    opposite_valid = [r["trigger"] for r in rows if r["verdict"] == "opposite_direction_same_level" and r.get("valid")]
    if sym is None:
        overall = "source_unresolved"
    elif str((plan or {}).get("symbol") or "").upper() not in ("", sym):
        overall = "different_symbol"
    elif best and causal is False:
        overall = "aligned_but_plan_predates_source"          # the plan could not have been informed by this source
    elif best and not best.get("valid"):
        overall = "aligned_trigger_rejected_by_our_gates"     # the source's branch exists in the plan but is NOT eligible
    elif best:
        overall = "aligned"
    elif any(r["verdict"].startswith(("same_direction", "same_level")) and r.get("valid") for r in rows):
        overall = "same_direction_not_aligned"                # an eligible trigger on the author's side, but not his level/family - NOT alignment
    elif any(r["verdict"] == "opposite_direction_same_level" for r in rows):
        overall = "opposite_direction"
    elif rows:
        overall = "ticker_only"
    else:
        overall = "no_triggers"
    return {"version": MATCHER_VERSION, "scenarioId": scenario["scenarioId"], "symbol": sym, "overall": overall, "alignedTrigger": (best or {}).get("trigger"),
            "oppositeValidAtSameLevel": opposite_valid, "causal": causal, "planBuiltAt": _iso(built), "sourceUsableAt": _iso(ua), "planOrigin": plan_origin, "triggers": rows,
            "note": "ticker-only or opposite-direction coincidences are never 'aligned'; every trigger of the plan is listed"}


# ------------------------------------------------------------------------------------------------ persistence
async def store_scenarios(session, *, note_id: str, revision_id: str, payload: dict, completed_at=None):
    """Append-only, idempotent by the artifact output key (revision, kind, input hash, config hash). Never touches the job,
    the note projection, positions or orders. Returns (row, reused)."""
    from ..models import TechniqueSourceArtifact
    from . import source_revisions as srcrev
    key = srcrev.artifact_key(revision_id, "scenarios", str(payload["inputHash"]), str(payload["configHash"]))
    row = await session.get(TechniqueSourceArtifact, key)
    if row is not None:
        return row, True
    row = TechniqueSourceArtifact(id=key, revision_id=revision_id, note_id=note_id, technique=srcrev.TECHNIQUE, kind="scenarios", version=1,
                                  config_hash=str(payload["configHash"]), input_hash=str(payload["inputHash"]), payload=payload,
                                  completed_at=srcrev.parse_ts(completed_at) or srcrev.utcnow())
    session.add(row)
    return row, False


async def source_for_note(session, note_id: str, revision_id: str | None = None) -> dict | None:
    """Assemble `build_scenarios` input from the immutable rows of ONE revision (default: the current one)."""
    from sqlalchemy import select
    from ..models import TechniqueMethodNote, TechniqueSourceArtifact, TechniqueSourceRevision
    from . import source_revisions as srcrev
    n = await session.get(TechniqueMethodNote, note_id)
    if n is None:
        return None
    rev = (await session.get(TechniqueSourceRevision, revision_id)) if revision_id else (await srcrev.current_revision(session, note_id))
    if rev is None:
        return None
    arts = (await session.execute(select(TechniqueSourceArtifact).where(TechniqueSourceArtifact.note_id == note_id).order_by(TechniqueSourceArtifact.created_at))).scalars().all()

    def newest(kind, same_rev_only):
        c = [a for a in arts if a.kind == kind and (a.revision_id == rev.id or not same_rev_only)]
        return c[-1] if c else None
    ex = newest("extraction", True)
    trn = newest("transcript", False)          # a transcript belongs to the media, which an edit of the caption does not change
    return {"note": {"id": n.id, "kind": n.kind, "messageId": n.message_id, "channelId": n.channel_id, "channelName": n.channel_name, "author": n.author},
            "revision": {"id": rev.id, "revision": rev.revision, "kind": rev.kind, "authorId": rev.author_id, "authorName": rev.author_name, "text": rev.text,
                         "publishedAt": rev.published_at, "receivedAt": rev.received_at, "deleted": rev.deleted},
            "transcript": ({"artifactId": trn.id, "text": (trn.payload or {}).get("text"), "completedAt": trn.completed_at} if trn is not None else None),
            "extraction": ({"artifactId": ex.id, "payload": dict(ex.payload or {}), "completedAt": ex.completed_at} if ex is not None else None)}
