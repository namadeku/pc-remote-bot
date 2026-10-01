import socket

import pytest

from pc_remote_bot import wol


@pytest.mark.parametrize("mac", ["04-7C-16-ED-7A-E0", "04:7c:16:ed:7a:e0", "047C16ED7AE0"])
def test_parse_mac_formats(mac: str) -> None:
    assert wol.parse_mac(mac) == bytes([0x04, 0x7C, 0x16, 0xED, 0x7A, 0xE0])


@pytest.mark.parametrize("mac", ["", "04-7C-16-ED-7A", "zz:7c:16:ed:7a:e0", "04-7C-16-ED-7A-E0-11"])
def test_parse_mac_rejects_invalid(mac: str) -> None:
    with pytest.raises(ValueError, match="Invalid MAC"):
        wol.parse_mac(mac)


def test_magic_packet_layout() -> None:
    packet = wol.build_magic_packet("04-7C-16-ED-7A-E0")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("047C16ED7AE0") * 16


def test_send_magic_packet_reaches_udp_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(2)
        port = listener.getsockname()[1]
        wol.send_magic_packet("04-7C-16-ED-7A-E0", "127.0.0.1", port)
        data, _ = listener.recvfrom(1024)
    assert data == wol.build_magic_packet("04-7C-16-ED-7A-E0")
