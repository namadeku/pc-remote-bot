"""Telegram handlers."""

import asyncio
import html
import io
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pc_remote_bot import system, wol
from pc_remote_bot.config import Settings

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]

# Telegram's limit is 4096; leave room for the <pre> wrapper.
MAX_TEXT = 3800

POWER_ACTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "shutdown": ("Выключить ПК", system.shutdown),
    "reboot": ("Перезагрузить ПК", system.reboot),
    "sleep": ("Перевести ПК в сон", system.sleep),
}


async def reply_output(message: Message, text: str, filename: str = "output.txt") -> None:
    """Send text as a <pre> block, or as a file when it is too long."""
    if not text:
        text = "(пусто)"
    if len(text) <= MAX_TEXT:
        await message.reply_text(f"<pre>{html.escape(text)}</pre>", parse_mode=ParseMode.HTML)
    else:
        await message.reply_document(io.BytesIO(text.encode("utf-8")), filename=filename)


class Bot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _commands(self) -> list[tuple[str, str, Handler]]:
        commands: list[tuple[str, str, Handler]] = [
            ("help", "Список команд", self.help),
        ]
        if self.settings.enable_wake:
            commands += [
                ("wake", "Включить ПК (Wake-on-LAN)", self.wake),
                ("ping", "Проверить, включён ли ПК", self.ping),
            ]
        if self.settings.enable_control:
            commands += [
                ("status", "CPU, память, диски, аптайм", self.status),
                ("screen", "Скриншот экрана", self.screen),
                ("lock", "Заблокировать экран", self.lock),
                ("sleep", "Сон", self.power),
                ("shutdown", "Выключить", self.power),
                ("reboot", "Перезагрузить", self.power),
                ("cancel", "Отменить выключение/перезагрузку", self.cancel),
                ("ps", "Топ процессов по памяти", self.ps),
                ("kill", "Завершить процесс: /kill chrome или /kill 1234", self.kill),
                ("cmd", "Выполнить PowerShell: /cmd Get-Date", self.cmd),
            ]
        return commands

    def build(self) -> Application:
        builder = ApplicationBuilder().token(self.settings.bot_token).concurrent_updates(True)
        if self.settings.proxy_url:
            builder = builder.proxy(self.settings.proxy_url).get_updates_proxy(
                self.settings.proxy_url
            )
        app = builder.post_init(self._post_init).build()

        owner = filters.User(user_id=self.settings.allowed_user_ids)
        app.add_handler(CommandHandler("start", self.help, filters=owner))
        for name, _, handler in self._commands():
            app.add_handler(CommandHandler(name, handler, filters=owner))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(~owner, self.unauthorized))
        app.add_error_handler(self.on_error)
        return app

    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands(
            [BotCommand(name, description) for name, description, _ in self._commands()]
        )
        if not self.settings.allowed_user_ids:
            log.warning("ALLOWED_USER_IDS is empty: the bot will ignore everyone")

    # --- common ---

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        lines = [f"/{name} — {description}" for name, description, _ in self._commands()]
        await update.message.reply_text("\n".join(lines))

    async def unauthorized(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return
        log.warning("Rejected user %s (@%s)", user.id, user.username)
        await message.reply_text(f"Нет доступа. Ваш Telegram ID: {user.id}")

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Handler failed", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(f"Ошибка: {context.error}")

    # --- wake ---

    async def wake(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        s = self.settings
        if not s.wol_mac:
            await update.message.reply_text("WOL_MAC не задан в .env")
            return
        if s.pc_host and await wol.is_host_up(s.pc_host):
            await update.message.reply_text("ПК уже включён")
            return
        wol.send_magic_packet(s.wol_mac, s.wol_host, s.wol_port)
        if not s.pc_host:
            await update.message.reply_text("Magic packet отправлен")
            return
        status = await update.message.reply_text("Magic packet отправлен, жду ответа ПК...")
        if await wol.wait_until_up(s.pc_host):
            await status.edit_text("ПК включился ✅")
        else:
            await status.edit_text("ПК не ответил за 2 минуты ❌")

    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        if not self.settings.pc_host:
            await update.message.reply_text("PC_HOST не задан в .env")
            return
        up = await wol.is_host_up(self.settings.pc_host)
        await update.message.reply_text("ПК включён ✅" if up else "ПК не отвечает ❌")

    # --- control ---

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        await reply_output(update.message, await asyncio.to_thread(system.status_text))

    async def screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        png = await asyncio.to_thread(system.screenshot_png)
        # Send as a document to avoid Telegram's photo compression.
        await update.message.reply_document(io.BytesIO(png), filename="screen.png")

    async def lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        system.lock()
        await update.message.reply_text("Экран заблокирован 🔒")

    async def power(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        action = update.message.text.split()[0].lstrip("/").split("@")[0]
        title, _ = POWER_ACTIONS[action]
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Да", callback_data=f"power:{action}"),
                    InlineKeyboardButton("Нет", callback_data="power:no"),
                ]
            ]
        )
        await update.message.reply_text(f"{title}?", reply_markup=keyboard)

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        assert query
        assert query.data
        if query.from_user.id not in self.settings.allowed_user_ids:
            await query.answer("Нет доступа", show_alert=True)
            return
        await query.answer()
        action = query.data.removeprefix("power:")
        if action not in POWER_ACTIONS:
            await query.edit_message_text("Отменено")
            return
        title, run = POWER_ACTIONS[action]
        run()
        if action == "sleep":
            await query.edit_message_text(f"{title}: выполняется")
        else:
            await query.edit_message_text(
                f"{title}: через {system.POWER_DELAY_S} с. Отменить: /cancel"
            )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        ok = system.cancel_shutdown()
        await update.message.reply_text("Отменено ✅" if ok else "Нечего отменять")

    async def ps(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        await reply_output(update.message, await asyncio.to_thread(system.top_processes))

    async def kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        if not context.args:
            await update.message.reply_text("Использование: /kill <имя или PID>")
            return
        killed = await asyncio.to_thread(system.kill, " ".join(context.args))
        await update.message.reply_text(
            "Завершены:\n" + "\n".join(killed) if killed else "Процесс не найден"
        )

    async def cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        parts = update.message.text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text("Использование: /cmd <команда PowerShell>")
            return
        log.info("cmd: %s", parts[1])
        code, output = await system.run_command(parts[1])
        header = "таймаут" if code is None else f"код выхода {code}"
        await reply_output(update.message, f"[{header}]\n{output}")
