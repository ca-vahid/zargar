"""Moved to `zargar.marketstructure.structure` (platform plan phase 1, 2026-08-27).
This shim keeps every existing import working; new code imports the library."""
from ..marketstructure import structure as _m

globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})
