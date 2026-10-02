"""Telegram handlers."""

import asyncio
import html
import io
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import NetworkError
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
from pc_remote_bot.net import RetryingRequest

log = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]

# Telegram's limit is 4096; leave room for the <pre> wrapper.
MAX_TEXT = 3800

POWER_ACTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "shutdown": ("Выключить ПК", system.shutdown),
    "reboot": ("Перезагрузить ПК", system.reboot),
    "sleep": ("Перевести ПК в сон", system.sleep),
}

# user_data key: what the next plain text message is for ("cmd", "ask" or "kill").
PENDING = "pending_input"

CANCEL_INPUT = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Отмена", callback_data="input:cancel")]]
)


@dataclass(frozen=True, slots=True)
class Action:
    command: str
    description: str
    handler: Handler
    # Reply keyboard button label; None means command only.
    button: str | None = None
    # Buttons with the same row id are placed on one keyboard row.
    row: int = 0


async def reply_output(
    message: Message, text: str, filename: str = "output.txt", pre: bool = True
) -> None:
    """Send text as a <pre> block (or plain text), or as a file when it is too long."""
    if not text:
        text = "(пусто)"
    if len(text) <= MAX_TEXT:
        if pre:
            await message.reply_text(f"<pre>{html.escape(text)}</pre>", parse_mode=ParseMode.HTML)
        else:
            await message.reply_text(text)
    else:
        await message.reply_document(io.BytesIO(text.encode("utf-8")), filename=filename)


class Bot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.actions = self._actions()
        self.buttons = {a.button: a for a in self.actions if a.button}

    def _actions(self) -> list[Action]:
        actions = [Action("help", "Список команд", self.help)]
        if self.settings.enable_wake:
            actions += [
                Action("wake", "Включить ПК (Wake-on-LAN)", self.wake, "⚡ Включить ПК", 1),
                Action("ping", "Проверить, включён ли ПК", self.ping, "📡 Проверить ПК", 1),
            ]
        if self.settings.enable_control:
            actions += [
                Action("status", "CPU, память, диски, аптайм", self.status, "📊 Статус", 2),
                Action("screen", "Скриншот экрана", self.screen, "🖥 Скриншот", 2),
                Action("ps", "Топ процессов по памяти", self.ps, "📋 Процессы", 3),
                Action(
                    "kill",
                    "Завершить процесс: /kill chrome или /kill 1234",
                    self.kill,
                    "❌ Завершить процесс",
                    3,
                ),
                Action("cmd", "Выполнить PowerShell: /cmd Get-Date", self.cmd, "⌨️ PowerShell", 4),
                Action("ask", "Спросить Claude: /ask вопрос", self.ask, "🤖 Спросить Claude", 4),
                Action("lock", "Заблокировать экран", self.lock, "🔒 Заблокировать", 4),
                Action("sleep", "Сон", self.sleep, "😴 Сон", 5),
                Action("reboot", "Перезагрузить", self.reboot, "🔄 Перезагрузка", 5),
                Action("shutdown", "Выключить", self.shutdown, "⏻ Выключить", 5),
                Action(
                    "cancel",
                    "Отменить выключение/перезагрузку",
                    self.cancel,
                    "↩️ Отменить выключение",
                    6,
                ),
            ]
        return actions

    def keyboard(self) -> ReplyKeyboardMarkup:
        rows: list[list[str]] = []
        last_row: int | None = None
        for action in self.actions:
            if action.button is None:
                continue
            if action.row != last_row:
                rows.append([])
                last_row = action.row
            rows[-1].append(action.button)
        return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

    def build(self) -> Application:
        proxy = self.settings.proxy_url
        builder = (
            ApplicationBuilder()
            .token(self.settings.bot_token)
            .concurrent_updates(True)
            .request(
                RetryingRequest(connect_timeout=10, read_timeout=20, write_timeout=20, proxy=proxy)
            )
        )
        if proxy:
            builder = builder.get_updates_proxy(proxy)
        app = builder.post_init(self._post_init).build()

        owner = filters.User(user_id=self.settings.allowed_user_ids)
        app.add_handler(CommandHandler("start", self.help, filters=owner))
        for action in self.actions:
            app.add_handler(CommandHandler(action.command, action.handler, filters=owner))
        app.add_handler(
            MessageHandler(owner & filters.Text(list(self.buttons)), self.on_keyboard_button)
        )
        app.add_handler(MessageHandler(owner & filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(~owner, self.unauthorized))
        app.add_error_handler(self.on_error)
        return app

    async def _post_init(self, app: Application) -> None:
        await app.bot.set_my_commands([BotCommand(a.command, a.description) for a in self.actions])
        if not self.settings.allowed_user_ids:
            log.warning("ALLOWED_USER_IDS is empty: the bot will ignore everyone")

    # --- common ---

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        lines = [f"/{a.command} — {a.description}" for a in self.actions]
        lines.append("\nИли пользуйтесь кнопками внизу 👇")
        await update.message.reply_text("\n".join(lines), reply_markup=self.keyboard())

    async def on_keyboard_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        assert context.user_data is not None
        # Pressing any button abandons a pending text input.
        context.user_data.pop(PENDING, None)
        await self.buttons[update.message.text].handler(update, context)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        assert context.user_data is not None
        pending = context.user_data.pop(PENDING, None)
        text = update.message.text.strip()
        if pending == "cmd":
            await self._run_cmd(update.message, text)
        elif pending == "ask":
            await self._ask(update.message, text)
        elif pending == "kill":
            await self._kill(update.message, text)
        else:
            await update.message.reply_text(
                "Не понял. Выберите действие кнопкой или /help", reply_markup=self.keyboard()
            )

    async def unauthorized(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return
        log.warning("Rejected user %s (@%s)", user.id, user.username)
        await message.reply_text(f"Нет доступа. Ваш Telegram ID: {user.id}")

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Handler failed", exc_info=context.error)
        if isinstance(context.error, NetworkError):
            # Telegram itself is unreachable, so an error reply would fail too.
            return
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(f"Ошибка: {context.error}")

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        assert query
        assert query.data
        if query.from_user.id not in self.settings.allowed_user_ids:
            await query.answer("Нет доступа", show_alert=True)
            return
        await query.answer()
        kind, _, value = query.data.partition(":")
        if kind == "input":
            assert context.user_data is not None
            context.user_data.pop(PENDING, None)
            await query.edit_message_text("Отменено")
        elif kind == "power":
            await self._do_power(query.edit_message_text, value)

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

    async def sleep(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ask_power(update, "sleep")

    async def reboot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ask_power(update, "reboot")

    async def shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._ask_power(update, "shutdown")

    async def _ask_power(self, update: Update, action: str) -> None:
        assert update.message
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

    async def _do_power(
        self, edit: Callable[[str], Coroutine[Any, Any, object]], action: str
    ) -> None:
        if action not in POWER_ACTIONS:
            await edit("Отменено")
            return
        title, run = POWER_ACTIONS[action]
        run()
        if action == "sleep":
            await edit(f"{title}: выполняется")
        else:
            await edit(
                f"{title}: через {system.POWER_DELAY_S} с. "
                "Отменить: кнопка «↩️ Отменить выключение» или /cancel"
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
        if context.args:
            await self._kill(update.message, " ".join(context.args))
            return
        assert context.user_data is not None
        context.user_data[PENDING] = "kill"
        await update.message.reply_text(
            "Пришлите имя процесса (например, chrome) или PID", reply_markup=CANCEL_INPUT
        )

    async def _kill(self, message: Message, target: str) -> None:
        killed = await asyncio.to_thread(system.kill, target)
        await message.reply_text(
            "Завершены:\n" + "\n".join(killed) if killed else "Процесс не найден"
        )

    async def cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        parts = update.message.text.split(maxsplit=1)
        if parts[0].startswith("/") and len(parts) == 2:
            await self._run_cmd(update.message, parts[1])
            return
        assert context.user_data is not None
        context.user_data[PENDING] = "cmd"
        await update.message.reply_text(
            "Пришлите команду PowerShell, например: Get-Date", reply_markup=CANCEL_INPUT
        )

    async def _run_cmd(self, message: Message, command: str) -> None:
        log.info("cmd: %s", command)
        code, output = await system.run_command(command)
        header = "таймаут" if code is None else f"код выхода {code}"
        await reply_output(message, f"[{header}]\n{output}")

    async def ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.message
        assert update.message.text
        parts = update.message.text.split(maxsplit=1)
        if parts[0].startswith("/") and len(parts) == 2:
            await self._ask(update.message, parts[1])
            return
        assert context.user_data is not None
        context.user_data[PENDING] = "ask"
        await update.message.reply_text("Напишите вопрос для Claude", reply_markup=CANCEL_INPUT)

    async def _ask(self, message: Message, prompt: str) -> None:
        log.info("ask: %s", prompt)
        await message.reply_text("🤖 Claude думает…")
        code, answer = await system.ask_claude(prompt)
        if code is None:
            answer = f"[таймаут]\n{answer}"
        elif code != 0:
            answer = f"[код выхода {code}]\n{answer}"
        await reply_output(message, answer, filename="answer.md", pre=False)
