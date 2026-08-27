"""EnhancedMarket technique pipeline.

Implements the trading method specified in `docs/techniques/enhanced-market/METHOD.md`.
Deterministic detection lives here; the vision/reasoning layer sits on top and
every number it produces is re-verified against these primitives.
"""
