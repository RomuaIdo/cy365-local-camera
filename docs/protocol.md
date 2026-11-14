# CS2 P2P (PPCS / PPPP) Protocol

## Overview

This document describes the CS2 peer-to-peer protocol (PPCS / PPPP) as used by a Wi-Fi IP camera. It covers LAN discovery, library initialization, the proprietary cipher, the packet framing, the CRC layer, login, control channel, video and audio reception. The information comes from decompilation of the vendor's native library (`libobject_jni.so`, arm64-v8a build) and from a LAN packet capture taken on a personal, non-commercial interoperability test with the owner's own camera.

Status: partially verified.

Legend:

| Tag | Meaning |
|---|---|
| [VERIFIED-DECOMP] | Read directly from the decompiled native library. |
| [HYPOTHESIS] | Deduced or inferred. Not yet confirmed against a camera or a packet capture. |

Unmarked statements that refer to a packet capture were confirmed against that capture.

Address convention: a Ghidra address equals the `nm -D` symbol offset plus `0x100000` (image base). Some addresses in the source material use a different base; they are reproduced as given.

## 1. Ports and LAN discovery

- The LAN search listens on UDP port **0x7d6c = 32108**. [VERIFIED-DECOMP] (`cs2p2p_PPPP_thread_recv_LanSearch`, Ghidra 0x1fc408, calls `cs2p2p_setup_listen_port(0x7d6c)`).
- The default P2P server is a `sockaddr_in` with port **0x647d -> 0x7d64 = 32100**. [VERIFIED-DECOMP] in `cs2p2p_PPPP_Initialize` (Ghidra 0x201bdc). The bytes are written as `0x647d` into a little-endian struct, which gives network port 32100. [HYPOTHESIS: byte order.]
- The list of P2P servers is a comma-separated `ParamString`, decoded by `cs2p2p_PPPP_DecodeString` (called from Initialize).

## 2. Initialize: parameter format (InitString)

[VERIFIED-DECOMP] `cs2p2p_PPPP_Initialize(param)`:

- Accepts JSON with the keys `MaxNumSess` (1..512, default 256), `SessAliveSec` (6..30, default 6), `P2PPunchRange` (0..10, default 3), `QuickListen` (0/1), `APILogFile`, and `InitString`.
- Or a plain string longer than 17 characters, in the form `<encoded servers>:<KEY>`. The P2P key is the text after the `:`, read up to 20 printable characters (0x21..0x7E) and stored in `cs2p2p_gP2PKeyString`.
- This key is used as the cipher key for the LAN search (`Proto_Recv_ALL(&cs2p2p_gP2PKeyString, ...)`) and as `key` in the Proprietary functions.

## 3. Proprietary cipher [VERIFIED-DECOMP]

Functions: `cs2p2p__P2P_Proprietary_Encrypt` / `cs2p2p__P2P_Proprietary_Decrypt(key, in, out, len)` (Ghidra 0x2132cc / 0x213444), `cs2p2p__P2P_Proprietary_SelectTableElement` (0x2132a8). The 256-byte S-box is located at Ghidra 0x7f5470 (vaddr 0x6f5470) and is extracted to `code/tables/p2p_sbox.bin`. It is a valid permutation.

Initial state: `st[4]` (4 bytes), set to 0. For each byte `c` of the key (up to 20 bytes; stops at the first 0 byte, using `strnlen(key,0x14)`), with `i` as the character index:

```
st0 = st0 + c              (mod 256)   [cVar2 = bVar1 + local_10 low byte]
st1 = st1 - c              (mod 256)
st2 = st2 + c / 3          (mod 256)   [bVar1 / 3]
st3 = st3 ^ c
```

The exact assignments are in the `local_10` lines of `cs2p2p__P2P_Proprietary_Encrypt`. [HYPOTHESIS: to be re-checked against the decompilation.]

Selection function:

```
Sel(b) = S[(b + st[b & 3]) & 0xFF]
```

Encrypt (feedback over the previous ciphertext byte):

```
out[0] = Sel(0) ^ in[0]
out[i] = Sel(out[i-1]) ^ in[i]        for i >= 1
```

Decrypt:

```
out[0] = Sel(0) ^ in[0]
out[i] = Sel(in[i-1]) ^ in[i]         for i >= 1   (feedback over the previous CIPHERTEXT byte)
```

If the key is empty, the data is copied without encryption.

Note: the first byte uses `Sel(&local_10, 0)`, which gives index `0 + st[0]` in the decompilation.

TCP Relay variant: `_TCPRelay_Proprietary_Encrypt(p, in, out, len)` builds the key as `sprintf("%02X%02X", p[0], p[1])` (4 uppercase hex characters from the first 2 bytes of `p`) and calls Proprietary_Encrypt. [VERIFIED-DECOMP]

## 4. Framing [VERIFIED-DECOMP]

**Session header (PPCS):** 4 bytes followed by the payload.

```
byte0 = 0xF1          (magic; Read_Header checks == -0xF)
byte1 = packet type
byte2..3 = payload length, big-endian (uint16)
```

Observed types:

| Type | Function | Payload length |
|---|---|---|
| 0x00 | Proto_Send_Hello | 0 (total 4 bytes) |
| 0x10 | Proto_Send_DevLgn | 0x28 (40) |
| 0xE0 | Proto_Send_Alive | 0 |
| 0xD0 | DRW (data with acknowledgement) | 4 + n |

**DRW header** (inside the payload of type 0xD0), 4 bytes:

```
byte0 = 0xD1         (magic; DRW_Read_Header checks == -0x2F)
byte1 = channel (param_4 of DRW_Send)
byte2..3 = sequence number, big-endian
```

Followed by n bytes of data.

**Special control messages** (received in Proto_Recv_ALL when the length is 0x11 and the first byte is 0): the ASCII strings `"338DB900E5592B32"` return -99 (0xffffff9d), and `"338DB900E559KILL"` returns -98 (0xffffff9e). Possibly a request and a shutdown message. [HYPOTHESIS]

## 5. Video and audio reception (CPPPPChannel layer)

`CPPPPChannel::DataProcess` (Ghidra 0x1dd100) [VERIFIED-DECOMP]:

- Reads the AV head of **32 bytes** (`local_88`, 0x20) with `HLP2P_Read` (if `this+0xe4 == 1`) or `PPCS_Read` (otherwise), timeout 100000 us. Partial reads are repeated.
- Log output shows the AV head fields `type`, `streamid`, `militime`, `sectime`, `len`, and `frameno`. The exact offsets are in `local_88`, `uStack_80`, and `local_78` of the decompilation. [HYPOTHESIS: to be confirmed with a packet capture.]
- Then reads `len` bytes of payload, in blocks of up to 0x8000 bytes.

The data thread `CPPPPChannel::DataThread` (0x1dcf0c) calls `AttachCurrentThread` and then `DataProcess`.

## 6. Open items (next steps)

1. Decompile `cs2p2p_PPPP_Write_Header` (sets byte0, type, and length for writing) and the payload of `cs2p2p_PPPP_Proto_Send_DevLgn` (`Write_DevLgn`), which defines the login.
2. Decompile `cs2p2p_PPPP_Connect` (0x20cf3c, 7 KB) and `cs2p2p_PPPP_Proto_Send_PunchPkt`, which define the handshake sequence.
3. Decompile `cs2p2p_PPPP_Proto_Read_DevLgn` (0x213df8) and `Proto_Read_RlyReq` / `Proto_Read_RlyPkt`, which define the login and relay responses.
4. Decompile `cs2p2p_PPPP_Read` (0x20e908, 22 KB) to confirm the user data path.
5. Decompile `CPPPPChannel::cgi_livestream` (see `_ZN12CPPPPChannel14cgi_livestreamEii`). The content of `GET /livestream.cgi` has so far been seen only as a string.
6. Validate the S-box dump (`code/tables/p2p_sbox.bin`) with at least one encrypt-decrypt round trip and, when a capture is available, with a known plaintext (for example an encrypted `GET /livestream`).

## 7. Risks

- The cipher is simple and has no strong key. If the key is the camera's InitString (from the app), its value is required. The app functions `SHIXGetAPPKey` and `StartPPPP`, and the license strings `:SHIX` and `:mycamera`, must be checked.

## 8. Second verification pass (2026-10-14)

Verified against the decompilation:

- `Proto_Write_DevLgn` (0x213d70) matches the 40-byte DevLgn layout: DID prefix 7B at @0, DID number BE32 at @8, DID suffix 7B at @0xC, mode 1B at @0x14, version 3B at @0x15, sockaddr 16B at @0x18.
  - **Observation:** the DevLgn packet does not contain a password. The 40 bytes hold identification and address data. User and password (`user` / `pwd`) authentication therefore happens later, on the DRW channel (JSON), or the camera validates only the DID. [HYPOTHESIS]
- The following functions exist under these names: `cs2p2p_PPPP_Proto_Send_HelloAck` (0x213cd0), `thread_recv_Proto` (0x204f08, dispatcher, 0x204f08-0x207213), `CRCSelect4Key` (0x212d5c), `cgi_livestream` (0x1def8c), `thread_recv_DRW` (0x202b44), and `Proto_Send_ReportSessionRdy` (0x217370).
- LAN search (0x1fc408): on receiving a packet of type `'0'` (0x30, LanSerch), it calls `Send_PunchPkt`. This confirms the LanSearch -> PunchPkt flow.
- Streaming: `cgi_livestream` exists. The exact JSON it sends has not yet been confirmed in the decompilation; it is known only from strings. [HYPOTHESIS]

Corrections to an earlier unverified report:

- The string `SSD@cs2-network.` is located at **0x7f2e20**, not at 0x217370. Address 0x217370 is the function `ReportSessionRdy`.
- `cs2p2p_CRCDec` (0x2046f4) is only 15 bytes long. It is a wrapper, not the complete decoder. The function it calls must be examined.
- Line-number references of the form `thread_recv_Proto:NNN` in the earlier report cannot be checked against the decompilation. Treat the assignment of message types to handlers as [HYPOTHESIS] until the dispatcher has been read.
- Several entries in the constants list pointed to files that do not exist. Only the addresses are used here.

A Python re-implementation of the cipher (`code/p2pcrypto.py`) matches the decompiled cipher. A round trip over 1000 random inputs succeeded 1000 of 1000 times. Compatibility with a real camera has not yet been demonstrated. [HYPOTHESIS]

## 9. Open items (next pass)

1. Read the dispatcher `thread_recv_Proto` (0x204f08). For each `case`, document the received type and the response sent. This yields the actual handshake state machine.
2. Read `CRCEnc` / `CRCDec` and the body of `CRCSelect4Key` (0x212d5c), together with the matrix at 0x7f5430. This is required for `DevLgn_CRC` (0x12) and `DevLgnAck_CRC` (0x13).
3. Determine where `user` / `pwd` enter the authentication flow (DRW / JSON or DevLgnAck).
4. Read `cgi_livestream` (0x1def8c) and confirm the JSON it sends.

## 10. Third pass: CRC layer [VERIFIED-DECOMP]

The 64-byte matrix M is located at Ghidra 0x7f5430 (ELF 0x6f5430). It was checked byte by byte against a memory dump of the binary.

State: s0, s1, s2, s3 (bytes). Initial state: 1, 3, 5, 7 (used when the key is NULL or empty). Otherwise, for each character `c` of the key (up to NUL, with no 20-byte limit): `(s0,s1,s2,s3) = Sel(c, s0,s1,s2,s3)`.

**CRCSelect4Key(a, b, c, d, e)** (a = p1 is the data or key byte; b..e = s0..s3). Let `mod(x,y) = x % y` if y != 0, otherwise `x`:

```
row1 = (mod(a,b) + c) % 8     col1 = (mod(d,e) + a) % 8     p6 = M[8*row1 + col1]
row2 = (mod(a,c) + d) % 8     col2 = (mod(e,b) + a) % 8     p7 = M[8*row2 + col2]
row3 = (mod(a,d) + e) % 8     col3 = (mod(b,c) + a) % 8     p8 = M[8*row3 + col3]
row4 = (mod(a,e) + b) % 8     col4 = (mod(c,d) + a) % 8     p9 = M[8*row4 + col4]
new state = (p6, p7, p8, p9)
```

**cs2p2p_PPPP_CRCEnc(in, n, out, outmax, key)** (0x212ec4): requires `n + 3 < outmax`, otherwise returns -1.

1. Initial state plus key mixing (above).
2. For each `in[i]`: `o = s0^s1^s2^s3^in[i]`; `out[i] = o`; `(s) = CRCSelect4Key(o, s0,s1,s2,s3)` (feedback over the CIPHERTEXT byte).
3. Trailer, 4 times: `o = s0^s1^s2^s3^0x43`; `out[n+j] = o`; update the state with `o`.
4. Returns n+4.

**cs2p2p_PPPP_CRCDec(in, n, out, outmax, key)** (0x21308c): `dec[i] = in[i]^s0^s1^s2^s3`, then update the state with `CRCSelect4Key(in[i], ...)` (feedback over the input ciphertext byte). Check: the last 4 decrypted bytes must be 0x43 (verified by a chained `if (__src[...] == 0x43)` test). If they are, the output is n-4 bytes; otherwise the result is -1. Returns 0 on success. The wrapper `cs2p2p_CRCDec` (0x2046f4) only passes `cs2p2p_gCRCKey`.

**Key cs2p2p_gCRCKey** (0x207b24, DO_APILicenseCheck_PPPP): the substring after the first `:` of the initialization string; empty if there is no `:`. This is the same `<blob>:<TAG>` structure as section 2. The TAG (SHIX, mycamera, camera, FERRY@88, XIAODOU) is the CRC key. [HYPOTHESIS: which TAG the CY365 model uses.]

**DevLgn_CRC (0x12)** (0x214148): `header(0x12, 0x2c)` followed by `CRCEnc(DevLgn40, 40, out, 0x2c, gCRCKey)`. This gives 44 bytes, which are sent with a 4-byte header for a total of 48 bytes. Confirmed.

Resolved ambiguities:

- Body of DevLgn at `buf+4`: confirmed. In the decompilation of `Proto_Send_DevLgn`, the buffer `abStack_108[4]` and `local_104[252]` are the same 256-byte block, and the body starts at offset +4.
- Byte order of the sockaddr: confirmed big-endian. `cs2p2p_htonAddr` (0x2137d4) writes family, port, and IP in big-endian order. The family is `00 02`, the port is BE16 (for example 32108 -> `7d 6c`), and the IP is BE32.

## 11. Fourth pass: initialization, key, and login (2026-10-15)

Verified against the decompilation:

- **CRC: initial state for a non-empty key = (1,3,5,7).** The decompilation of `CRCEnc` (0x212ec4) sets 1,3,5,7 before the key loop. This resolves the ambiguity noted in section 10.
- **Low injectivity of the CRC is a property of the formula.** The four formulas in section 10 are the ones in the decompilation. Input `a` enters only through `+a mod 8`. This may be intended design. [HYPOTHESIS: to be tested with the camera.]
- **`getServer` (0x1c99f4) confirmed** by direct reading of the `strcmp` chain. The DID prefix (uppercase letters up to the first non-alphabetic character, computed in `StartPPPP` 0x1cb35c) maps to a tag string:
  - `DGOA..DGOF`, `DGOG..DGOK`, `DGKA` / `DGKB` / `DGKC`, `DGB`, `DGHA`, ... -> TAG `camera`
  - `FFF`, `EEE`, `ABC`, `ABCF`, `DDD`, `AAA`, `XIAODOU`, `HBW`, `NNN`, `PIXA..PIXD` -> TAG `SHIX`
  - `PPSL` / `PPLL` / `PPIL` -> `mycamera`; `THPC` -> `hyWHzyhtzH`; `FYPPCS` / `FYRTOS` / `FYIOT` -> `FERRY@88`
  - **Any other prefix (default) -> `camera`.**
  - For a standard CY365 camera (a DID that is not in the SHIX lists), the key is `camera`. If the DID starts with EEE, DDD, AAA, FFF, PIX, or XIAODOU, the key is `SHIX`.
- **Date guard in `PPPPInitial`** (JNI 0x1ca4e8): the function calls `PPCS_Initialize` only if `tm_year < 0x78` (year before 2020) and `tm_mon < 12`. With a current date in 2026, the function does not initialize the library and only writes a log message. The string passed from Java (`"test"`) is ignored, and the init string is fixed: `EDHNFGBILOINGGIG...:camera`.
  - `NativeCaller.Init()` (0x1ca95c) is a no-op that only logs.
  - Consequence: the original app probably does not initialize the library on this date. For this project's client, calling `cs2p2p_PPPP_Initialize` directly is sufficient. The native function `cs2p2p_PPPP_Initialize` (0x201bdc) does not have this date check (verified in section 2). [HYPOTHESIS: to be tested with the camera.]
- Factory default credentials are defined in the app source (`ContentCommon.java`, lines 179-180): the default user name is <user>, and the default password is <password> (4 digits).

Reported in an earlier report, NOT yet verified:

- `user` / `pwd` enter the DRW channel 0 as JSON: `{"pro":"check_user","cmd":100,"devmac":...,"user":...,"pwd":...}`. The string exists at 0x7efbb7, so the JSON is present. The framing has not been verified.
- An 8-byte header `06 0a a0 80 | len LE32` precedes the JSON (CommandProcess 0x1dc6d4 / cgi_get_common 0x1d7780). [HYPOTHESIS]
- The response `{"result":..,"admin":..,"mode":..,"type":..}` is processed by JasonProcessCheckUser (0x1d9794).

## 12. Next practical step: LAN probe

With the camera connected to the same Wi-Fi network, a LanSearch packet (`F1 30 00 00`) sent as a UDP broadcast to port 32108 should elicit a response from the camera (PunchPkt, type 0x41; see section 8). This is a passive and safe test, performed on the owner's own camera. If the camera responds, the port, the framing, and the fact that the native library speaks this protocol are all confirmed.

## 13. LAN probe on the owner's camera (2026-10-15): no response

- The camera is connected to a domestic Wi-Fi network. Its device identifier (DID) starts with the prefix `EEE` (the full value is redacted), which maps to TAG `SHIX` through `getServer`. Key: CRC / P2P `SHIX`. [HYPOTHESIS]
- Local host: <host-ip> (wlan0), /24.
- `code/lan_probe.py`: LanSearch `F1 30 00 00` sent 3 times to 255.255.255.255 and 192.168.1.255, port 32108, listening for 15 s. Result: **0 responses** (only the echo of the probe's own packets, which was filtered out).
- `nmap -sn`: 7 hosts found. Other LAN hosts were found; addresses are omitted. The camera was one of them.
- Unicast LanSearch to the 5 candidates on ports 32108 and 32100, listening for 6 s. Result: **0 responses**.
- nmap TCP scan on ports 80, 81, 554, 8000, and 8080: only one other host had 8000/tcp open (http-alt). No UDP ports 32100 or 32108 were detected as open (nmap -sU, inconclusive).
- Interpretations, not yet resolved:
  - (a) the camera does not answer LanSearch without a prior handshake or the correct key;
  - (b) LanSearch is encrypted and key-dependent on some firmware versions;
  - (c) the camera's IP address is not one of the candidates;
  - (d) the firmware differs from the original app. The owner reported that the original app failed and that an alternative app from the same vendor was used.
- Next step that resolves the question: capture traffic from the alternative app (or from the original app when it connects) with Wireshark or tcpdump on the same network, filtering for UDP and for ports 32100 and 32108 and the camera's address. The capture shows the first real packet and the camera's IP address.

## 14. Camera password (2026-10-15)

- The app shows the camera with a 4-digit password, provided by the owner. The value is not recorded in this document.
- Relation to the code: the factory default in the app is `SHIX_DEFUALT_PWD = <password>` (ContentCommon.java:179), which is also 4 digits. The default user is <user>.
- This matches the `pwd` field of the `check_user` JSON (section 11). There is not yet any evidence of how the camera validates this password.

## 15. Captured app traffic (2026-10-15)

Tool: `code/analyze_pcap.py`. The camera on the LAN has address <camera-ip>. Phone: port 29474. Camera: port 29528. The source data is a packet capture taken with a phone capture app (not included in this repository).

**Cipher confirmed with real traffic:** `p2pcrypto.encrypt(b"SHIX", ...)` reproduces exactly the first 4 bytes of:

- the phone's LanSearch `F1 30 00 00` -> `9f a1 ee b9` (broadcast 255.255.255.255:32108);
- the Hello `F1 00 00 00` -> `9f 91 2a 19` (server 32100).

These are two independent 4-byte matches. The session key is **SHIX**. All 3280 packets decrypt with a valid F1 header.

- **Why the LAN probe received no response:** the probe sent LanSearch in clear text. The camera and app expect the packet encrypted with SHIX.

**Packet types observed (decrypted):** F1 41 (PunchPkt, phone to camera), F1 42 (P2PRdy, camera to phone), F1 E0 / E1 (Alive / AliveAck), F1 F0 (Close), F1 D0 (DRW), F1 D1 (DRW header).

**Control channel (DRW channel 0), decrypted:**

- DRW frame: `F1 D0 len | D1 00 seq(2) | 06 0a a0 80 (cmd) | len LE32 | JSON` (phone to camera). The camera's response uses `06 0a a1 80`. This confirms the 8-byte framing described in section 11.
- Authentication: `{"pro":"check_user","cmd":100,"devmac":"0000","user":"<user>","pwd":"***"}`. Response: `{"cmd":100,"admin":1,"result":0,"type":2020,"mode":2020,"checkstr":"SHIX","checkver":3}`. `result:0` means login accepted. `checkstr` is "SHIX", the same key.
- Commands observed: `stream` cmd 111 (video 1/0, audio 1/0, camsmode 0), `get_cloudsupport` cmd 9000, and `set_cypush` cmd 1.
- The `set_cypush` JSON contains account-specific fields. These fields are intentionally omitted from this document.

**DevLgn (P2PRdy and PunchPkt):** the 20-byte payload after the F1 header carries the DID. It has the prefix `EEE` (bytes 0-2), a number in BE32 at offset 8, and a suffix (offsets 12-16). The decoded number does not match the numeric part of the DID as it appears in the device label, so the 20-byte structure may use a different encoding, or it may differ from the 40-byte DevLgn in section 8. The decoded value is redacted here. [HYPOTHESIS: to be tested.]

**Video (channel 1, DRW):** each frame begins with a 32-byte header, located inside the DRW payload after `D1 01 seq`:

- `55 aa 15 a8` = frame magic (0xA815AA55 little-endian);
- +4: 0x03 (frame type? [HYPOTHESIS]);
- +8: timestamp (0x6AD02BC6 [HYPOTHESIS]);
- +12: 0x014A on the first frame, growing by about 1 per frame (counter? [HYPOTHESIS]). This is NOT the JPEG size: it does not match the FFD9 end marker in any frame;
- +16: 0x4778 (sequence? [HYPOTHESIS]); the rest is zero.

After the header comes a **JPEG** image (FF D8 ... FF D9). From the capture, 166 frames were reconstructed and 143 complete JPEG frames were extracted. In this model, the video is **MJPEG, not H.264**. Visual inspection of an extracted frame showed a real camera image (dark scene). The missing frames cross packet boundaries (reordering or loss in the capture), not cipher errors.

**Public P2P servers (port 32100):** the phone queries 8.129.214.91, 8.131.242.166, 101.32.177.97, 3.227.45.161, 3.10.99.101, and 139.9.86.167, all on port 32100. These servers reply with short packets encrypted with SHIX.

**Consequences for this project's client:**

1. A direct LAN connection works without the P2P server. It requires only the camera's address and the SHIX key.
2. For the client: send DevLgn or PunchPkt encrypted with SHIX, then check_user (encrypted), then stream cmd 111. The video arrives as JPEG data after the 32-byte header.
3. The items marked [HYPOTHESIS] in the video header and the 20-byte DevLgn must be confirmed before a from-scratch implementation.

## 16. Working LAN client (2026-10-15)

Run: `code/cy_client.py --cam <camera-ip> --pwd <password> --out <output-dir> --seconds 30`.

Result: the encrypted LanSearch succeeded. The camera replies from an ephemeral port (for example 12804, 14210, or 18057); the port changes each session, so the client must use the port of the reply. PunchPkt and P2PRdy succeeded. check_user returned result 0. Stream cmd 111 produced **282 JPEG frames** in 30 s from the live camera.

**Cause of the stalled stream (fixed):** the camera uses a DRW window with acknowledgements. Without ACKs, it only repeated the packets with sequence 0 and 1 (1488 packets, 0 frames).

- ACK format (confirmed from the app's traffic, 814 packets): `F1 D1 | len BE16 | D1 channel | n BE16 | n x seq BE16`, where len = 4 + 2n. Example: `f1 d1 00 06 d1 01 00 01 00 12` = channel 1, sequence 0x12.
- The client now acknowledges each received DRW packet (channels 0 and 1).

**Port bug (fixed):** the `--port` option overwrote the port of the LanSearch reply.

**Pending:** the raw channel 1 packet dump (about 5 MB, for offline analysis) can be deleted when no longer needed. The frames of about 1.7 KB and 3.5 KB (frames 163 and 256) are too small for a 640x480 JPEG. They are probably partial or low-quality frames, and this needs to be checked.

## 17. Broken frames (2026-10-15)

Verified against a raw dump of channel 1 packets (not included): 5105 packets; 264 sequence jumps (for example 45 -> 19, 20 -> 46, 62 -> 46); 49 of 371 frames have a gap inside. Small frames (for example 163 and 256) are fragments: the top part of the image and the rest black. The cause was assembly in arrival order, with out-of-order and lost packets.

### Correction to section 17

- No packet was lost. Sequence numbers 0..4862 are all present in the dump. The "gaps" were reordering, and the repeats are retransmissions (242 duplicates).
- Unique frames in the dump: 281. Complete frames: 280 (1 discarded, the last one, which has no end).
- The ACK is SELECTIVE (a list of sequence numbers) and there is no NACK. Retransmissions come from sender timeouts (RTO about 4-18 ms). The observed window allows up to 18 unacknowledged packets. The median ACK delay is about 3 ms after the packet.
- The client now uses `code/video_assemble.py` (`VideoAssembler`, window = 300). It accepts `--view PORT` to show the video at http://127.0.0.1:PORT via `code/cy_viewer.py`.

## 18. Audio: codec is IMA ADPCM, not A-law (2026-10-15)

- The codec type 0x0b in the AV header of channel 2 uses `CAdpcm::ADPCMDecode` (0x1d30fc), not `ADecode` (A-law). Confirmed by disassembly of `CPPPPChannel::AudioProces`.
- Nibble order: high nibble first (lag-1 correlation 0.95, against 0.91 for the low-first order, reproduced in this work).
- Decoder state is reset for each frame (predictor 0, index 0). When the state carries over between frames, the output overflows (RMS 16629, peak 32768). With the reset, RMS is 343 and peak is 7949, a plausible ambient level. [To be confirmed by listening to the WAV.]
- Test WAV: 39680 samples, 8 kHz, 16-bit, mono, decoded from real app traffic in a packet capture (not included in this repository).
- Hypothesis to verify: the camera may send a state header per frame. The reset to zero was chosen because it gives a plausible level. [HYPOTHESIS]
