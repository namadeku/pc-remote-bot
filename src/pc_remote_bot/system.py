"""Actions on the local Windows PC."""

import asyncio
import datetime as dt
import subprocess
import sys

import mss
import mss.tools
import psutil

POWER_DELAY_S = 30
CMD_TIMEOUT_S = 60

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


async def run_command(command: str, timeout_s: int = CMD_TIMEOUT_S) -> tuple[int | None, str]:
    """Run a PowerShell command. Returns (exit code or None on timeout, output)."""
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        # Force UTF-8 output so Cyrillic text survives decoding.
        f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; {command}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return None, f"Таймаут {timeout_s} с, процесс остановлен"
    return proc.returncode, stdout.decode("utf-8", errors="replace").strip()
