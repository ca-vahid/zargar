__version__ = "0.7.71"


def build_sha() -> str:
    """The checkout's short commit SHA (cached), so two builds that share a version string are
    distinguishable on /api/health (reviewer re-review 2026-09-14). ZARGAR_BUILD overrides."""
    import os
    if getattr(build_sha, "_v", None):
        return build_sha._v
    v = os.environ.get("ZARGAR_BUILD") or ""
    if not v:
        try:
            import subprocess
            v = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                               cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.strip() or "unknown"
        except Exception:
            v = "unknown"
    build_sha._v = v
    return v
