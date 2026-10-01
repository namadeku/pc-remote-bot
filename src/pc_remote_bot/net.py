"""HTTP transport for outgoing Bot API calls that survives short network drops."""

import asyncio
import logging
from typing import Any

import httpx
from telegram.error import NetworkError
from telegram.request import HTTPXRequest

log = logging.getLogger(__name__)

RETRY_DELAYS_S = (1.0, 3.0, 6.0)


def is_connect_failure(err: BaseException) -> bool:
    """True when the request never reached Telegram, so resending can't duplicate it."""
    return isinstance(err.__cause__, httpx.ConnectError | httpx.ConnectTimeout)


class RetryingRequest(HTTPXRequest):
    """Retries a call when the TCP/TLS connection to Telegram could not be established."""

    def __init__(self, retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.retry_delays_s = retry_delays_s

    async def do_request(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        for delay in self.retry_delays_s:
            try:
                return await super().do_request(*args, **kwargs)
            except NetworkError as err:  # TimedOut is a subclass
                if not is_connect_failure(err):
                    raise
                log.warning("Telegram unreachable (%r), retrying in %.0f s", err, delay)
                await asyncio.sleep(delay)
        return await super().do_request(*args, **kwargs)
