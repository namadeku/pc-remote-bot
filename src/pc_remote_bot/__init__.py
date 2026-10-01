import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pc_remote_bot.bot import Bot
from pc_remote_bot.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    else:
        # Started via pythonw (autostart): no console, write to a file in the project root.
        log_file = Path(__file__).resolve().parents[2] / "bot.log"
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        )
    logging.basicConfig(format=LOG_FORMAT, level=logging.INFO, handlers=handlers)
    # httpx logs every getUpdates request at INFO, and the URL contains the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    settings = Settings.from_env()
    # Retry forever: after logon Wi-Fi/VPN may not be up yet.
    Bot(settings).build().run_polling(bootstrap_retries=-1)
