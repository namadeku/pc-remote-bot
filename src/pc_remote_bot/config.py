"""Settings loaded from environment variables (and a .env file next to the project)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from pc_remote_bot.wol import parse_mac


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_user_ids(value: str) -> frozenset[int]:
    return frozenset(int(part) for part in value.replace(" ", "").split(",") if part)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int]
    enable_control: bool
    enable_wake: bool
    wol_mac: str | None
    wol_host: str
    wol_port: int
    pc_host: str | None
    proxy_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is not set (copy env.example to .env)")

        wol_mac = os.environ.get("WOL_MAC", "").strip() or None
        if wol_mac:
            parse_mac(wol_mac)  # fail fast on a typo

        return cls(
            bot_token=token,
            allowed_user_ids=parse_user_ids(os.environ.get("ALLOWED_USER_IDS", "")),
            enable_control=_bool(os.environ.get("ENABLE_CONTROL"), default=True),
            enable_wake=_bool(os.environ.get("ENABLE_WAKE"), default=wol_mac is not None),
            wol_mac=wol_mac,
            wol_host=os.environ.get("WOL_HOST", "").strip() or "255.255.255.255",
            wol_port=int(os.environ.get("WOL_PORT", "").strip() or "9"),
            pc_host=os.environ.get("PC_HOST", "").strip() or None,
            proxy_url=os.environ.get("PROXY_URL", "").strip() or None,
        )
