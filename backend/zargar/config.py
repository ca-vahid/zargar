"""Process-level configuration (env / .env). Runtime-tunable settings live in the DB
(see settings_service) — this module is only for things needed before the DB is up."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZARGAR_", env_file=".env", extra="ignore")

    # --- database -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://zargar:zargar@127.0.0.1:5432/zargar"
    db_echo: bool = False

    # --- api server ------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8420
    # Static bearer token (scripts / CLI). Empty = not used.
    auth_token: str = ""
    # --- sign-in (SSO) ---------------------------------------------------
    # Google OAuth client id (Cloud Console -> Credentials -> OAuth client, Web).
    # Set -> the app requires sign-in; only the allow-listed emails get in.
    google_client_id: str = ""
    google_allowed_emails: str = ""      # comma-separated, e.g. "you@gmail.com"
    session_secret: str = ""             # HS256 secret for session cookies; empty = generated + kept in settings
    session_days: int = 30
    # With neither auth_token nor google_client_id set the API is open (local dev only).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- broker ----------------------------------------------------------
    # Which broker backend serves live/paper portfolios: "sim" | "ibkr"
    broker: str = "sim"
    # Where quotes come from: "auto" (ibkr if connected, else yahoo when
    # SnapTrade is active, else sim) | "sim" | "yahoo"
    quote_source: str = "auto"
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4002  # 4002 gateway paper, 4001 gateway live, 7497 TWS paper
    ibkr_client_id: int = 17

    # --- sim engine ------------------------------------------------------
    sim_tick_interval: float = 0.35  # seconds between simulated ticks per symbol batch
    sim_seed: int = 0  # 0 = random each run; fixed value = deterministic quotes
    sim_history_minutes: int = 2 * 24 * 60  # synthesized 1m-bar history per symbol

    # --- integrations ----------------------------------------------------
    # SnapTrade personal API credentials (dashboard → API Key page). Used for
    # Wealthsimple/Webull access; see zargar.tools.snaptrade_check.
    snaptrade_client_id: str = ""
    snaptrade_consumer_key: str = ""
    anthropic_api_key: str = ""
    extraction_model: str = "claude-opus-5"
    # Alpaca market data (Algo Trader Plus = full-SIP websocket). With both keys
    # set, US-listed quotes/1m bars stream from Alpaca and Yahoo drops back to
    # non-US symbols, session context and history. Keys: app.alpaca.markets.
    alpaca_key_id: str = ""
    alpaca_secret: str = ""
    # Tradier developer token for options chains (free tier: developer.tradier.com).
    tradier_token: str = ""
    tradier_sandbox: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Shared secret required on the inbound email webhook (X-Zargar-Ingest-Key header).
    ingest_key: str = ""
    # HMAC mode for the webhook (NEXT-GAPS W1): when set, the POST body must be
    # signed — X-Zargar-Signature = hex(HMAC-SHA256(secret, raw body)); unsigned
    # or mis-signed requests are rejected. Stronger than the static key (the
    # signature never travels and covers the payload). Env, not settings: it
    # guards the pre-auth boundary.
    ingest_hmac_secret: str = ""

    # --- misc --------------------------------------------------------------
    frontend_dist: str = ""  # path to built SPA; served at / when set


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
