"""Actions on the local Windows PC."""

import asyncio
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

import mss
import mss.tools
import psutil

POWER_DELAY_S = 30
CMD_TIMEOUT_S = 60
CLAUDE_TIMEOUT_S = 300
CLAUDE_DIR = Path.home() / ".pc-remote-bot" / "claude"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run_detached(*args: str) -> None:
    subprocess.Popen(args, creationflags=_NO_WINDOW)


def shutdown(delay_s: int = POWER_DELAY_S) -> None:
    _run_detached("shutdown", "/s", "/t", str(delay_s))


def reboot(delay_s: int = POWER_DELAY_S) -> None:
    _run_detached("shutdown", "/r", "/t", str(delay_s))


def cancel_shutdown() -> bool:
    result = subprocess.run(
        ["shutdown", "/a"], capture_output=True, check=False, creationflags=_NO_WINDOW
    )
    return result.returncode == 0


def sleep() -> None:
    # Goes to hibernation instead of sleep if hibernation is enabled.
    _run_detached("rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0")


def lock() -> None:
    _run_detached("rundll32.exe", "user32.dll,LockWorkStation")


def screenshot_png() -> bytes:
    """Screenshot of all monitors combined."""
    with mss.MSS() as sct:
        shot = sct.grab(sct.monitors[0])
        png = mss.tools.to_png(shot.rgb, shot.size)
    assert png is not None
    return png


def format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


def status_text() -> str:
    boot = dt.datetime.fromtimestamp(psutil.boot_time())
    uptime = dt.datetime.now() - boot
    mem = psutil.virtual_memory()
    lines = [
        f"CPU: {psutil.cpu_percent(interval=0.5):.0f}%",
        f"RAM: {format_bytes(mem.used)} / {format_bytes(mem.total)} ({mem.percent:.0f}%)",
    ]
    for part in psutil.disk_partitions():
        if "cdrom" in part.opts or not part.fstype:
            continue
        usage = psutil.disk_usage(part.mountpoint)
        lines.append(
            f"Диск {part.mountpoint} свободно {format_bytes(usage.free)}"
            f" из {format_bytes(usage.total)}"
        )
    battery = psutil.sensors_battery()
    if battery is not None:
        plug = ", от сети" if battery.power_plugged else ""
        lines.append(f"Батарея: {battery.percent:.0f}%{plug}")
    lines.append(f"Аптайм: {str(uptime).split('.')[0]} (с {boot:%d.%m %H:%M})")
    return "\n".join(lines)


def top_processes(limit: int = 15) -> str:
    procs: list[tuple[int, str, int]] = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        mem = p.info["memory_info"]
        if mem is None:
            continue
        procs.append((mem.rss, p.info["name"] or "?", p.info["pid"]))
    procs.sort(reverse=True)
    return "\n".join(
        f"{pid:>6}  {format_bytes(rss):>9}  {name}" for rss, name, pid in procs[:limit]
    )


def kill(target: str) -> list[str]:
    """Kill by PID or by process name (case-insensitive, .exe optional)."""
    if target.isdigit():
        procs = [psutil.Process(int(target))]
    else:
        name = target.lower().removesuffix(".exe")
        procs = [
            p
            for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower().removesuffix(".exe") == name
        ]
    killed: list[str] = []
    for p in procs:
        try:
            p.kill()
            killed.append(f"{p.pid} {p.name()}")
        except psutil.Error:
            continue
    return killed


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        procs = [*parent.children(recursive=True), parent]
    except psutil.Error:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            continue


async def _communicate(
    args: list[str], timeout_s: int, stdin: bytes | None = None, cwd: Path | None = None
) -> tuple[int | None, str]:
    """Run a process, merging stderr into stdout. Kills the whole tree on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
        cwd=cwd,
        creationflags=_NO_WINDOW,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(stdin), timeout_s)
    except TimeoutError:
        _kill_tree(proc.pid)
        await proc.wait()
        return None, f"Таймаут {timeout_s} с, процесс остановлен"
    return proc.returncode, stdout.decode("utf-8", errors="replace").strip()


async def run_command(command: str, timeout_s: int = CMD_TIMEOUT_S) -> tuple[int | None, str]:
    """Run a PowerShell command. Returns (exit code or None on timeout, output)."""
    return await _communicate(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            # Force UTF-8 output so Cyrillic text survives decoding.
            f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; {command}",
        ],
        timeout_s,
    )


async def ask_claude(
    prompt: str, new_chat: bool = False, timeout_s: int = CLAUDE_TIMEOUT_S
) -> tuple[int | None, str]:
    """Ask Claude Code in non-interactive mode. Returns (exit code or None on timeout, answer).

    Continues the bot's previous conversation unless new_chat is set.
    """
    exe = shutil.which("claude")
    if exe is None:
        return 1, "Claude Code не найден в PATH"
    # --continue picks the latest conversation in the working folder, so the bot gets
    # a folder of its own and never resumes the user's interactive sessions.
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    args = [exe, "-p"] if new_chat else [exe, "-p", "--continue"]
    # The prompt goes through stdin so quotes and newlines need no escaping.
    return await _communicate(args, timeout_s, stdin=prompt.encode("utf-8"), cwd=CLAUDE_DIR)
