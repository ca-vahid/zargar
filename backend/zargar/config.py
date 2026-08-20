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
    # Static bearer token. Empty string disables auth (local development).
    auth_token: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- broker ----------------------------------------------------------
    # Which broker backend serves live/paper portfolios: "sim" | "ibkr"
    broker: str = "sim"
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
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Shared secret required on the inbound email webhook (X-Zargar-Ingest-Key header).
    ingest_key: str = ""

    # --- misc --------------------------------------------------------------
    frontend_dist: str = ""  # path to built SPA; served at / when set


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
