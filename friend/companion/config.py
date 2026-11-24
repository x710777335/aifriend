"""Configuration and safe logging setup."""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    use_mock_llm: bool
    base_url: str
    model: str
    api_key: str | None
    context_turns: int
    database_path: Path
    log_path: Path
    avatar_dir: Path
    audio: "AudioSettings"
    asr: "AsrSettings"
    tts: "TtsSettings"
    interaction: "VoiceInteractionSettings"
    server: "ServerSettings"


@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 16000
    channels: int = 1
    vad_silence_ms: int = 3000
    vad_prebuffer_ms: int = 300
    vad_min_speech_ms: int = 400
    vad_max_speech_s: int = 30
    vad_start_ms: int = 96
    input_device: str = "default"


@dataclass(frozen=True)
class AsrSettings:
    provider: str = "funasr"
    model: str = "iic/SenseVoiceSmall"
    device: str = "cpu"
    language: str = "zh"
    timeout_s: int = 45


@dataclass(frozen=True)
class TtsSettings:
    provider: str = "edge_tts"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    enabled: bool = True


@dataclass(frozen=True)
class VoiceInteractionSettings:
    mode: str = "half_duplex"
    auto_listen_after_reply: bool = True
    ignore_microphone_during_tts: bool = True


@dataclass(frozen=True)
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 8765
    device_token: str | None = None
    allow_test_stt: bool = False


def _bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_settings(root: Path = ROOT) -> Settings:
    """Load local settings, then apply environment overrides. No secrets are logged."""
    load_dotenv(root / ".env")
    file_config: dict[str, object] = {}
    config_file = root / "config.toml"
    if config_file.exists():
        with config_file.open("rb") as handle:
            file_config = tomllib.load(handle)

    def value(name: str, default: object) -> object:
        # Public env names follow OpenAI convention for provider settings.
        env_name = {"base_url": "OPENAI_BASE_URL", "model": "OPENAI_MODEL"}.get(name, name.upper())
        return os.getenv(env_name, file_config.get(name, default))

    def section(name: str) -> dict[str, object]:
        candidate = file_config.get(name, {})
        return candidate if isinstance(candidate, dict) else {}

    audio = section("audio")
    asr = section("asr")
    tts = section("tts")
    interaction = section("interaction")
    server = section("server")

    return Settings(
        use_mock_llm=_bool(value("use_mock_llm", True), True),
        base_url=str(value("base_url", "https://api.openai.com/v1")),
        model=str(value("model", "gpt-4o-mini")),
        api_key=os.getenv("OPENAI_API_KEY"),
        context_turns=max(1, int(value("context_turns", 8))),
        database_path=root / "data" / "chat_history.sqlite3",
        log_path=root / "logs" / "app.log",
        avatar_dir=root / "assets" / "avatars",
        audio=AudioSettings(**{key: audio[key] for key in AudioSettings.__dataclass_fields__ if key in audio}),
        asr=AsrSettings(**{key: asr[key] for key in AsrSettings.__dataclass_fields__ if key in asr}),
        tts=TtsSettings(**{key: tts[key] for key in TtsSettings.__dataclass_fields__ if key in tts}),
        interaction=VoiceInteractionSettings(**{
            key: interaction[key] for key in VoiceInteractionSettings.__dataclass_fields__ if key in interaction
        }),
        server=ServerSettings(
            host=str(os.getenv("FRIEND_SERVER_HOST", server.get("host", "0.0.0.0"))),
            port=int(os.getenv("FRIEND_SERVER_PORT", server.get("port", 8765))),
            device_token=os.getenv("FRIEND_DEVICE_TOKEN"),
            allow_test_stt=_bool(os.getenv("FRIEND_ALLOW_TEST_STT", server.get("allow_test_stt", False)), False),
        ),
    )


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
