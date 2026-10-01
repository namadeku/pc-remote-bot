from dataclasses import replace

from telegram.ext import CommandHandler

from pc_remote_bot.bot import Bot
from pc_remote_bot.config import Settings

BASE = Settings(
    bot_token="123:abc",
    allowed_user_ids=frozenset({42}),
    enable_control=True,
    enable_wake=False,
    wol_mac=None,
    wol_host="255.255.255.255",
    wol_port=9,
    pc_host=None,
    proxy_url=None,
)


def registered_commands(settings: Settings) -> set[str]:
    app = Bot(settings).build()
    return {
        command
        for handler in app.handlers[0]
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }


def test_control_mode_commands() -> None:
    commands = registered_commands(BASE)
    assert {"status", "screen", "shutdown", "cmd"} <= commands
    assert "wake" not in commands


def test_wake_only_mode_commands() -> None:
    settings = replace(BASE, enable_control=False, enable_wake=True, wol_mac="04-7C-16-ED-7A-E0")
    commands = registered_commands(settings)
    assert {"wake", "ping"} <= commands
    assert "cmd" not in commands
