import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pc_remote_bot import system


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (512, "512 B"),
        (2048, "2.0 KB"),
        (5 * 1024**3, "5.0 GB"),
        (3 * 1024**5, "3072.0 TB"),
    ],
)
def test_format_bytes(n: int, expected: str) -> None:
    assert system.format_bytes(n) == expected


def test_status_text_has_main_lines() -> None:
    text = system.status_text()
    assert "CPU:" in text
    assert "RAM:" in text
    assert "Аптайм:" in text


def test_top_processes_limit() -> None:
    assert len(system.top_processes(limit=3).splitlines()) == 3


def test_screenshot_is_png() -> None:
    assert system.screenshot_png().startswith(b"\x89PNG")


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell on Windows")
async def test_run_command_utf8() -> None:
    code, output = await system.run_command("Write-Output 'привет'")
    assert code == 0
    assert output == "привет"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell on Windows")
async def test_run_command_timeout() -> None:
    code, _ = await system.run_command("Start-Sleep 5", timeout_s=1)
    assert code is None


async def test_ask_claude_without_claude_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system.shutil, "which", lambda _: None)
    code, output = await system.ask_claude("hi")
    assert code == 1
    assert "не найден" in output


@pytest.mark.parametrize(("new_chat", "has_continue"), [(False, True), (True, False)])
async def test_ask_claude_continue_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, new_chat: bool, has_continue: bool
) -> None:
    communicate = AsyncMock(return_value=(0, "ok"))
    monkeypatch.setattr(system.shutil, "which", lambda _: "claude.exe")
    monkeypatch.setattr(system, "_communicate", communicate)
    monkeypatch.setattr(system, "CLAUDE_DIR", tmp_path / "claude")
    await system.ask_claude("hi", new_chat=new_chat)
    call = communicate.await_args
    assert call is not None
    assert ("--continue" in call.args[0]) is has_continue
    assert call.kwargs["cwd"] == tmp_path / "claude"
    assert (tmp_path / "claude").is_dir()
