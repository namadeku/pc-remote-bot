import logging

from pc_remote_bot.bot import Bot
from pc_remote_bot.config import Settings


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx logs every getUpdates request at INFO, and the URL contains the token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    Bot(settings).build().run_polling()
