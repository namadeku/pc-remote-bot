import sys
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import CommandHandler

from pc_remote_bot.bot import PENDING, Bot
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


def test_keyboard_layout() -> None:
    rows = [[button.text for button in row] for row in Bot(BASE).keyboard().keyboard]
    assert rows[0] == ["📊 Статус", "🖥 Скриншот"]
    assert rows[-2] == ["😴 Сон", "🔄 Перезагрузка", "⏻ Выключить"]
    assert all("Включить ПК" not in text for row in rows for text in row)


def test_wake_keyboard_has_only_wake_buttons() -> None:
    settings = replace(BASE, enable_control=False, enable_wake=True, wol_mac="04-7C-16-ED-7A-E0")
    rows = [[button.text for button in row] for row in Bot(settings).keyboard().keyboard]
    assert rows == [["⚡ Включить ПК", "📡 Проверить ПК"]]


def fake_update(text: str) -> MagicMock:
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def fake_context() -> MagicMock:
    context = MagicMock()
    context.user_data = {}
    context.args = None
    return context


def replies(update: MagicMock) -> list[Any]:
    return [call.args[0] for call in update.message.reply_text.await_args_list]


async def test_button_dispatches_to_handler() -> None:
    bot = Bot(BASE)
    update, context = fake_update("❌ Завершить процесс"), fake_context()
    await bot.on_keyboard_button(update, context)
    assert context.user_data[PENDING] == "kill"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell on Windows")
async def test_powershell_button_then_text_runs_command() -> None:
    bot = Bot(BASE)
    context = fake_context()
    await bot.on_keyboard_button(fake_update("⌨️ PowerShell"), context)
    assert context.user_data[PENDING] == "cmd"

    update = fake_update("Write-Output 'hi'")
    await bot.on_text(update, context)
    assert PENDING not in context.user_data
    assert "hi" in replies(update)[0]


async def test_other_button_clears_pending_input() -> None:
    bot = Bot(BASE)
    context = fake_context()
    context.user_data[PENDING] = "cmd"
    await bot.on_keyboard_button(fake_update("😴 Сон"), context)
    assert PENDING not in context.user_data


async def test_unexpected_text_shows_hint() -> None:
    bot = Bot(BASE)
    update = fake_update("привет")
    await bot.on_text(update, fake_context())
    assert "кнопкой" in replies(update)[0]
