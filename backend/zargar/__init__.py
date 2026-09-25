__version__ = "0.8.48"


def _read_build() -> str:
    """The build identifier, bound ONCE at import (= process launch): full commit SHA of the checkout the
    code was loaded from, suffixed `-dirty` when the working tree had uncommitted changes, `unknown`
    when git is unavailable. ZARGAR_BUILD overrides (a packaged deploy sets it). Read lazily on a later
    call it could describe a checkout that moved after launch (reviewer follow-up 2026-09-14)."""
    import os
    v = os.environ.get("ZARGAR_BUILD") or ""
    if v:
        return v
    try:
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, cwd=root).stdout.strip()
        if not sha:
            return "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True,
                               timeout=10, cwd=root).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


BUILD = _read_build()


def build_sha() -> str:
    return BUILD
