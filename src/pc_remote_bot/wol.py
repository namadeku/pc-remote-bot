"""Wake-on-LAN: build and send magic packets, check whether a host is up."""

import asyncio
import re
import socket
import sys

_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:\-.]?[0-9a-fA-F]{2}){5}$")


def parse_mac(mac: str) -> bytes:
    """Parse a MAC like 04-7C-16-ED-7A-E0, 04:7c:16:ed:7a:e0 or 047c16ed7ae0."""
    mac = mac.strip()
    if not _MAC_RE.match(mac):
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return bytes.fromhex(re.sub(r"[:\-.]", "", mac))


def build_magic_packet(mac: str) -> bytes:
    """6 bytes of 0xFF followed by the MAC repeated 16 times."""
    return b"\xff" * 6 + parse_mac(mac) * 16


def send_magic_packet(mac: str, host: str = "255.255.255.255", port: int = 9) -> None:
    """Send a magic packet. `host` is a broadcast address in the LAN, or a public
    address/hostname when the router forwards the UDP port to the LAN broadcast."""
    packet = build_magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (host, port))


def ping_command(host: str, timeout_s: int = 1) -> list[str]:
    if sys.platform == "win32":
        return ["ping", "-n", "1", "-w", str(timeout_s * 1000), host]
    return ["ping", "-c", "1", "-W", str(timeout_s), host]


async def is_host_up(host: str, timeout_s: int = 1) -> bool:
    """Single ICMP ping. Windows firewall must allow inbound echo requests."""
    proc = await asyncio.create_subprocess_exec(
        *ping_command(host, timeout_s),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    # Windows ping returns 0 for "Destination host unreachable" too, so check for TTL.
    return proc.returncode == 0 and b"TTL=" in stdout.upper()


async def wait_until_up(host: str, timeout_s: int = 120, interval_s: int = 5) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await is_host_up(host):
            return True
        await asyncio.sleep(interval_s)
    return False
