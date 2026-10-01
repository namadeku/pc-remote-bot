import socket

import pytest

from pc_remote_bot import wol


@pytest.mark.parametrize("mac", ["02-AB-CD-EF-12-34", "02:ab:cd:ef:12:34", "02ABCDEF1234"])
def test_parse_mac_formats(mac: str) -> None:
    assert wol.parse_mac(mac) == bytes([0x02, 0xAB, 0xCD, 0xEF, 0x12, 0x34])


@pytest.mark.parametrize("mac", ["", "02-AB-CD-EF-12", "zz:ab:cd:ef:12:34", "02-AB-CD-EF-12-34-11"])
def test_parse_mac_rejects_invalid(mac: str) -> None:
    with pytest.raises(ValueError, match="Invalid MAC"):
        wol.parse_mac(mac)


def test_magic_packet_layout() -> None:
    packet = wol.build_magic_packet("02-AB-CD-EF-12-34")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("02ABCDEF1234") * 16


def test_send_magic_packet_reaches_udp_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(2)
        port = listener.getsockname()[1]
        wol.send_magic_packet("02-AB-CD-EF-12-34", "127.0.0.1", port)
        data, _ = listener.recvfrom(1024)
    assert data == wol.build_magic_packet("02-AB-CD-EF-12-34")
