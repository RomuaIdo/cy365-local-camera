# References: PPPP / CS2 / P2P IP camera protocols

## Scope and status

This project's scope is local-network control of a camera that the user owns. The list below collects community and security-research prior art on the PPPP-family peer-to-peer protocols (CS2 Network, Yi, iLnk, and related rebrands) and on the cipher and framing these cameras use. It is a reading list, not an endorsement of any project, vendor, or claim. Entries were checked against the cited page or repository as noted; details may have changed since.

## Projects and articles

| Project or article | URL | What it documents or implements | Relevance |
|---|---|---|---|
| Overview of the PPPP protocol for IoT cameras (palant.info, 2025-11) | https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/ | Variants (CS2 Network, Yi, AJCloud, iLnk, HLP2P), init-string obfuscation via PPPP_DecodeString, XOR-style message obfuscation, and the method used (app and firmware reverse engineering) | protocol, cipher, framing, discovery |
| magicus/pppp-dissector | https://github.com/magicus/pppp-dissector | Wireshark Lua dissector for PPPP, a draft protocol spec (PPPP.md) with a table of pre-shared keys by device prefix; MIT license | protocol, framing, PSK |
| DavidVentura/cam-reverse | https://github.com/DavidVentura/cam-reverse | Re-implementation of the iLnk / iLnkP2P / PPPP protocol for low-cost X5/A9-class cameras (TXW817 chip); describes control and data packet split by the Drw command | protocol, framing, video |
| fbertone/lib32100 | https://github.com/fbertone/lib32100 | JavaScript library for the UDP port 32100 cloud protocol used by many P2P cameras, built from reverse engineering; MIT license | discovery, protocol |
| aiopppp (PyPI) | https://pypi.org/project/aiopppp/ | Async Python client for PPPP cameras (A9, X5): live video, PTZ, JSON and binary control variants, lists tested device-ID prefixes; Apache-2.0 | protocol, video, discovery |
| Wireshark dissector for the P2P protocol (hacked.camera) | https://hacked.camera/dissector/ | Describes a dissector for the PPPP protocol used by CS2 Network P2P and Shenzhen Yunni iLnkP2P; links to the dissector source | protocol, framing |
| pmarrapese/iot | https://github.com/pmarrapese/iot | IoT security research resources tagged p2p and pppp; includes a p2p folder (no license shown) | protocol (partial) |
| go2rtc Wyze source documentation | https://go2rtc.org/internal/wyze/ | Local streaming from Wyze cameras over the native P2P (TUTK) protocol without the vendor app; lists connection parameters (uid, enr, mac, model, subtype, DTLS) | video, discovery, cipher (DTLS) |
| SEC Consult, "Xiong-Who?! And Why We Care" | https://sec-consult.com/en/blog/2018/10/millions-of-xiongmai-video-surveillance-devices-can-be-hacked-via-cloud-feature-xmeye-p2p-cloud/ | Xiongmai / XMEye cloud protocol: reverse engineering of the app-to-cloud protocol and a scanner for valid cloud IDs; related but not PPPP | discovery, security context |

## Legal and ethical context

- Interoperability work here is limited to a camera the user owns, on the user's own local network. It does not use a vendor cloud, a relay, or any third-party service.
- Several cited sources describe weaknesses, including predictable cloud identifiers derived from device addresses. They are cited for background only. Do not use them to access devices you do not own or are not authorized to test.
- Do not redistribute vendor firmware, app binaries, or extracted key tables. Reference the protocol behavior, and check each project's license before reusing its code.
