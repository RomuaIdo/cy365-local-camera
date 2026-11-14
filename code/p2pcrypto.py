"Proprietary P2P cipher (CS2 PPCS/PPPP). Spec: notes/protocol-findings.md, section 3."
import os

_SBOX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tables", "p2p_sbox.bin"
)


def _load_sbox():
    with open(_SBOX_PATH, "rb") as f:
        data = f.read()
    if len(data) != 256:
        raise ValueError(f"p2p_sbox.bin must be 256 bytes, has {len(data)}")
    return data


SBOX = _load_sbox()


def key_state(key: bytes) -> bytes:
    "Four-byte state derived from the key (up to 20 bytes, stops at the first 0)."
    st = [0, 0, 0, 0]
    for c in key[:20]:
        if c == 0:
            break
        st[0] = (st[0] + c) & 0xFF
        st[1] = (st[1] - c) & 0xFF
        st[2] = (st[2] + c // 3) & 0xFF
        st[3] ^= c
    return bytes(st)


def _select(st: bytes, b: int) -> int:
    # Sel(b) = S[(b + st[b & 3]) & 0xFF]
    return SBOX[(b + st[b & 3]) & 0xFF]


def _is_empty_key(key: bytes) -> bool:
    # The decompile treats a key whose first byte is 0 as empty.
    return not key or key[0] == 0


def encrypt(key: bytes, data: bytes) -> bytes:
    if _is_empty_key(key):
        return bytes(data)
    if not data:
        return b""
    st = key_state(key)
    out = bytearray(len(data))
    out[0] = _select(st, 0) ^ data[0]
    for i in range(1, len(data)):
        # feedback from the previous ciphertext byte
        out[i] = _select(st, out[i - 1]) ^ data[i]
    return bytes(out)


def decrypt(key: bytes, data: bytes) -> bytes:
    if _is_empty_key(key):
        return bytes(data)
    if not data:
        return b""
    st = key_state(key)
    out = bytearray(len(data))
    out[0] = _select(st, 0) ^ data[0]
    for i in range(1, len(data)):
        # feedback from the previous ciphertext input
        out[i] = _select(st, data[i - 1]) ^ data[i]
    return bytes(out)


def tcprelay_key(first2: bytes) -> bytes:
    "TCP relay key: 4 uppercase hex characters from 2 bytes."
    return f"{first2[0]:02X}{first2[1]:02X}".encode()


# ---- Proprietary CRC ----
# Spec: notes/protocol-findings.md, section 10 (CRCEnc 0x212ec4,
# cs2p2p_PPPP_CRCDec 0x21308c, CRCSelect4Key 0x212d5c).

_CRC_MATRIX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tables", "p2p_crc_matrix.bin"
)


def _load_crc_matrix():
    with open(_CRC_MATRIX_PATH, "rb") as f:
        data = f.read()
    if len(data) != 64:
        raise ValueError(f"p2p_crc_matrix.bin must be 64 bytes, has {len(data)}")
    return data


CRC_MATRIX = _load_crc_matrix()
CRC_INIT_STATE_NULL_KEY = (1, 3, 5, 7)  # NULL or empty key
# [HYPOTHESIS] initial state for a non-empty key: the spec does not say. With (0,0,0,0)
# mixing the key gives (v,v,v,v) and the state XOR stays 0 (output = input,
# constant trailer). So (1,3,5,7) is used until the spec is confirmed.
CRC_INIT_STATE_KEY = (1, 3, 5, 7)
CRC_TRAILER_BYTE = 0x43


def _mod(x: int, y: int) -> int:
    # mod(x,y) = x % y if y != 0, else x
    return x % y if y else x


def crc_select4key(a, b, c, d, e):
    "CRCSelect4Key(a, s0, s1, s2, s3) -> new state (p6, p7, p8, p9)."
    a, b, c, d, e = (v & 0xFF for v in (a, b, c, d, e))
    row1 = (_mod(a, b) + c) % 8
    col1 = (_mod(d, e) + a) % 8
    p6 = CRC_MATRIX[8 * row1 + col1]
    row2 = (_mod(a, c) + d) % 8
    col2 = (_mod(e, b) + a) % 8
    p7 = CRC_MATRIX[8 * row2 + col2]
    row3 = (_mod(a, d) + e) % 8
    col3 = (_mod(b, c) + a) % 8
    p8 = CRC_MATRIX[8 * row3 + col3]
    row4 = (_mod(a, e) + b) % 8
    col4 = (_mod(c, d) + a) % 8
    p9 = CRC_MATRIX[8 * row4 + col4]
    return p6, p7, p8, p9


def _crc_state(key):
    "Initial state plus key mixing (up to NUL, no 20-byte limit)."
    if key is None or not key or key[0] == 0:
        return CRC_INIT_STATE_NULL_KEY
    s = CRC_INIT_STATE_KEY
    for c in key:
        if c == 0:
            break
        s = crc_select4key(c, *s)
    return s


def crc_enc(data: bytes, key) -> bytes:
    "Returns len(data)+4 bytes. The outmax check (n+3 < outmax) is not applied."
    s0, s1, s2, s3 = _crc_state(key)
    out = bytearray()
    for x in data:
        o = s0 ^ s1 ^ s2 ^ s3 ^ x
        out.append(o)
        s0, s1, s2, s3 = crc_select4key(o, s0, s1, s2, s3)
    for _ in range(4):
        o = s0 ^ s1 ^ s2 ^ s3 ^ CRC_TRAILER_BYTE
        out.append(o)
        s0, s1, s2, s3 = crc_select4key(o, s0, s1, s2, s3)
    return bytes(out)


def crc_dec(data: bytes, key) -> bytes:
    "Decrypts and checks the trailer (last 4 decrypted bytes == 0x43). Returns n-4 bytes."
    if len(data) < 4:
        raise ValueError("input shorter than the 4-byte trailer")
    s0, s1, s2, s3 = _crc_state(key)
    dec = bytearray()
    for x in data:
        dec.append(x ^ s0 ^ s1 ^ s2 ^ s3)
        s0, s1, s2, s3 = crc_select4key(x, s0, s1, s2, s3)
    if list(dec[-4:]) != [CRC_TRAILER_BYTE] * 4:
        raise ValueError("invalid CRC trailer")
    return bytes(dec[:-4])


def devlgn_crc_payload(devlgn40: bytes, key) -> bytes:
    "DevLgn_CRC (0x12): 40-byte CRCEnc -> 44 bytes."
    if len(devlgn40) != 40:
        raise ValueError("DevLgn must be 40 bytes")
    return crc_enc(devlgn40, key)
