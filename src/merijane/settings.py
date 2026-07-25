from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseModel):
    username: str = "MeriJane34"
    accept_challenges: bool = True
    accept_bot_challenges: bool = False
    casual_only_while_testing: bool = False
    allowed_variants: list[str] = Field(default_factory=lambda: ["standard"])
    allowed_speeds: list[str] = Field(
        default_factory=lambda: ["blitz", "rapid", "classical"]
    )
    min_increment_seconds: int = 0
    max_concurrent_games: int = 1
    session_game_limit: int | None = None


class EngineConfig(BaseModel):
    multipv: int = 6
    move_time_ms: dict[str, int] = Field(
        default_factory=lambda: {"blitz": 700, "rapid": 1500, "classical": 2500}
    )
    threads: int = 2
    hash_mb: int = 256
    skill_level: int = 15
    max_cp_loss: int = 125
    target_rapid_elo: int = 2150
    mate_score: int = 100000


class PersonalityConfig(BaseModel):
    base_anxiety: float = 0.28
    base_confidence: float = 0.62
    base_risk_tolerance: float = 0.43
    creativity: float = 0.58
    italian_preference: float = 1.0
    opening_familiarity_bonus: float = 0.34
    safety_bonus: float = 0.22
    complexity_penalty: float = 0.18
    exchange_bonus_when_ahead: float = 0.20
    randomness_temperature: float = 0.16
    panic_cap: float = 0.18
    recovery_rate: float = 0.30


class ChatConfig(BaseModel):
    enabled: bool = True
    win_probability_for_battery_joke: float = 0.88
    battery_joke_probability: float = 0.18
    max_messages_per_game: int = 3


class LoggingConfig(BaseModel):
    save_games: bool = True
    save_chat: bool = True
    save_engine_eval: bool = True
    export_pgn: bool = True
    export_csv: bool = True
    lichess_games_dir: Path = Path("data/lichess_games")


class AppConfig(BaseModel):
    bot: BotConfig
    engine: EngineConfig
    personality: PersonalityConfig
    chat: ChatConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    lichess_bot_token: str
    stockfish_path: Path
    merijane_config: Path = Path("config/merijane.yml")


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle)
    return AppConfig.model_validate(raw)
