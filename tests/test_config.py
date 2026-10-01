import pytest

from pc_remote_bot import config
from pc_remote_bot.config import Settings, parse_user_ids


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the real .env in the project root out of the tests.
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    for name in (
        "BOT_TOKEN",
        "ALLOWED_USER_IDS",
        "ENABLE_CONTROL",
        "ENABLE_WAKE",
        "WOL_MAC",
        "WOL_HOST",
        "WOL_PORT",
        "PC_HOST",
        "PROXY_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_parse_user_ids() -> None:
    assert parse_user_ids("1, 2,3,") == frozenset({1, 2, 3})
    assert parse_user_ids("") == frozenset()


def test_requires_token() -> None:
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        Settings.from_env()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    s = Settings.from_env()
    assert s.enable_control
    assert not s.enable_wake
    assert s.wol_host == "255.255.255.255"
    assert s.wol_port == 9


def test_wake_enabled_by_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("WOL_MAC", "04-7C-16-ED-7A-E0")
    monkeypatch.setenv("ENABLE_CONTROL", "false")
    s = Settings.from_env()
    assert s.enable_wake
    assert not s.enable_control


def test_bad_mac_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("WOL_MAC", "nope")
    with pytest.raises(ValueError, match="Invalid MAC"):
        Settings.from_env()
