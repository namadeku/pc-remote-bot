import httpx
import pytest
from telegram.error import TimedOut

from pc_remote_bot.net import RetryingRequest

URL = "https://api.telegram.org/bot123:abc/getMe"


def flaky_transport(failures: list[Exception]) -> tuple[httpx.MockTransport, list[int]]:
    """Raises the given errors in order, then answers 200. Also counts calls."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if failures:
            raise failures.pop(0)
        return httpx.Response(200, json={"ok": True, "result": {}})

    return httpx.MockTransport(handler), calls


def make_request(transport: httpx.MockTransport, attempts: int = 3) -> RetryingRequest:
    return RetryingRequest(retry_delays_s=(0.0,) * attempts, httpx_kwargs={"transport": transport})


async def test_retries_connect_failures_then_succeeds() -> None:
    transport, calls = flaky_transport(
        [httpx.ConnectTimeout("timeout"), httpx.ConnectError("refused")]
    )
    request = make_request(transport)
    code, _ = await request.do_request(URL, "POST")
    assert code == 200
    assert len(calls) == 3


async def test_gives_up_after_all_attempts() -> None:
    transport, calls = flaky_transport([httpx.ConnectTimeout("timeout")] * 10)
    request = make_request(transport, attempts=2)
    with pytest.raises(TimedOut):
        await request.do_request(URL, "POST")
    assert len(calls) == 3


async def test_does_not_retry_after_request_was_sent() -> None:
    # A read timeout means Telegram may have processed the call: resending could duplicate it.
    transport, calls = flaky_transport([httpx.ReadTimeout("slow")])
    request = make_request(transport)
    with pytest.raises(TimedOut):
        await request.do_request(URL, "POST")
    assert len(calls) == 1
