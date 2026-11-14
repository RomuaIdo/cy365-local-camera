"PPCS/PPPP framing (no network). Spec: notes/protocol-findings.md, sections 4 and 8."
import socket
import struct

MAGIC_SESSION = 0xF1
MAGIC_DRW = 0xD1

T_HELLO = 0x00
T_DEVLGN = 0x10
T_LANSEARCH = 0x30
T_ALIVE = 0xE0
T_DRW = 0xD0

DEVLGN_LEN = 40


def build_session(ptype: int, payload: bytes = b"") -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("payload larger than 65535 bytes")
    return bytes([MAGIC_SESSION, ptype]) + struct.pack(">H", len(payload)) + payload


def parse_session(data: bytes):
    "Returns (ptype, payload). Raises ValueError if the header is invalid."
    if len(data) < 4:
        raise ValueError("packet shorter than the 4-byte header")
    if data[0] != MAGIC_SESSION:
        raise ValueError(f"invalid magic: 0x{data[0]:02X} (expected 0xF1)")
    (length,) = struct.unpack(">H", data[2:4])
    if length != len(data) - 4:
        raise ValueError(f"header length {length} != payload {len(data) - 4}")
    return data[1], data[4:]


def build_drw(channel: int, seq: int, data: bytes) -> bytes:
    if not 0 <= channel <= 0xFF:
        raise ValueError("channel out of 0..255")
    if not 0 <= seq <= 0xFFFF:
        raise ValueError("seq out of 0..65535")
    drw = bytes([MAGIC_DRW, channel]) + struct.pack(">H", seq) + data
    return build_session(T_DRW, drw)


def parse_drw(payload: bytes):
    "Takes the payload of a 0xD0 packet and returns (channel, seq, data)."
    if len(payload) < 4:
        raise ValueError("DRW payload shorter than 4 bytes")
    if payload[0] != MAGIC_DRW:
        raise ValueError(f"invalid DRW magic: 0x{payload[0]:02X} (expected 0xD1)")
    (seq,) = struct.unpack(">H", payload[2:4])
    return payload[1], seq, payload[4:]


def build_hello() -> bytes:
    return build_session(T_HELLO)


def build_lan_search() -> bytes:
    return build_session(T_LANSEARCH)


def build_alive() -> bytes:
    return build_session(T_ALIVE)


def _pad7(value: bytes, name: str) -> bytes:
    # strncpy of 7 bytes: truncate and pad with \0
    if len(value) > 7:
        raise ValueError(f"{name} longer than 7 bytes")
    return value.ljust(7, b"\x00")


def build_devlgn(did_prefix: bytes, did_number: int, did_suffix: bytes,
                 mode: int, version: bytes, ip: str, port: int) -> bytes:
    "Builds the full DevLgn packet (4-byte header + 40-byte body). Layout per proto_headers.c."
    if not 0 <= did_number <= 0xFFFFFFFF:
        raise ValueError("did_number out of uint32 range")
    if not 0 <= mode <= 0xFF:
        raise ValueError("mode out of 0..255")
    if len(version) != 3:
        raise ValueError("version must be exactly 3 bytes")
    if not 0 <= port <= 0xFFFF:
        raise ValueError("port out of 0..65535")
    body = bytearray(DEVLGN_LEN)
    body[0:7] = _pad7(did_prefix, "did_prefix")
    struct.pack_into(">I", body, 8, did_number)
    body[12:19] = _pad7(did_suffix, "did_suffix")
    body[20] = mode
    body[21:24] = version
    struct.pack_into(">HH", body, 24, 2, port)
    body[28:32] = socket.inet_aton(ip)
    # body[32:40] is already zero
    return build_session(T_DEVLGN, bytes(body))


def parse_devlgn(payload: bytes):
    "Inverse of build_devlgn: takes the 40-byte payload and returns its fields."
    if len(payload) != DEVLGN_LEN:
        raise ValueError(f"DevLgn must be {DEVLGN_LEN} bytes, has {len(payload)}")
    did_prefix = payload[0:7]
    (did_number,) = struct.unpack(">I", payload[8:12])
    did_suffix = payload[12:19]
    mode = payload[20]
    version = payload[21:24]
    family, port = struct.unpack(">HH", payload[24:28])
    if family != 2:
        raise ValueError(f"unexpected sockaddr family: {family}")
    ip = socket.inet_ntoa(payload[28:32])
    return did_prefix, did_number, did_suffix, mode, version, ip, port
