# CY365 Local Camera Panel

A local, cloud-free control panel and protocol library for a Wi-Fi IP camera that uses the
CS2 / PPCS / PPPP peer-to-peer protocol on the local network.

The project talks to a camera **that you own**, on **your own network**. It does not use the
vendor cloud, does not require an account, and does not redistribute vendor firmware or apps.

> Status: the protocol is only partly documented. The implementation was built from packet
> captures and decompilation analysis of the vendor app, and it has been tested against a single
> camera model. See [docs/protocol.md](docs/protocol.md) for what is verified and what is not.

## Features

- Local discovery (LanSearch) and login over UDP, with the vendor cipher and framing reimplemented
  in pure Python (no third-party packages).
- Live MJPEG video, with out-of-order packet reassembly and duplicate suppression.
- Live audio: the camera's IMA ADPCM stream is decoded and played in the browser in real time.
- Read-only probe of the camera capabilities, with masked output.
- Local web panel (single HTML file, no CDN): live view, snapshots, audio, indicator and infrared
  controls, device information, network information.
- Offline test suites for every module, plus headless-browser checks for the panel.

## Repository layout

| Path | Contents |
|---|---|
| `code/` | Protocol library (`p2pcrypto.py`, `p2pframe.py`, `cy_session.py`, `video_assemble.py`) and command-line tools |
| `code/tables/` | Constant tables used by the cipher (S-box and CRC matrix) |
| `app/` | Local HTTP server (`servidor.py`) and the web panel (`app/static/index.html`) |
| `docs/` | Protocol notes, capability report, feature catalogue, UI specification and design, references |

The `captures/` folder is not part of the repository. It holds packet captures and camera output
from your own setup. Tests that need it are skipped when it is missing.

## Requirements

- Python 3 with the standard library only (developed and tested with Python 3.14).
- Google Chrome or Chromium, and Node.js 22 or newer, only for the browser tests (`*.mjs`).

## Configuration

The camera needs two values that are specific to your device. They are not stored in this
repository:

- **Device identifier (DID)**: the UID printed on the camera label or shown in the vendor app,
  in the form `PPPNNNNNNSSSSS` (3 letters, 6 digits, 5 letters).
- **Camera password**: the local access password configured in the camera.

Set the identifier through the environment variable `CAMERA_DID`, for example:

```sh
export CAMERA_DID=ABC123456DEFGH
```

The password is only given on the command line (`--pwd`) or typed in the web panel. It is never
written to disk or to logs.

## Quick start

Run the offline test suites (no camera needed):

```sh
python3 -I -B code/cy_session.py --testes
python3 -I -B code/probe_leitura.py --testes
python3 -I -B code/teste_audio.py --testes
python3 -I -B app/servidor.py --testes
```

Read-only probe of the camera capabilities (first print the plan, which sends nothing):

```sh
python3 -I -B code/probe_leitura.py --plano
python3 -I -B code/probe_leitura.py --pwd <password>
```

Run the web panel:

```sh
python3 -I -B app/servidor.py --port 8080
# then open http://127.0.0.1:8080/
```

To try the panel without a camera, run the fake-camera server and open the same address:

```sh
python3 -I -B app/teste_servidor_falso.py 8080 --audio-feed
```

## Safety

- Commands that change the camera (settings, Wi-Fi, firmware, reboot) require explicit
  confirmation in the API (`"confirmed": true`) and in the command-line scripts (`--confirmar`).
- The probe only sends read commands (`get_*`) and refuses anything else.
- The server listens on `127.0.0.1` and rejects requests whose `Host` header is not local.
- Do not point these tools at a camera you do not own.

## Documentation

- [docs/protocol.md](docs/protocol.md): packet framing, cipher, login, video and audio channels.
- [docs/camera-capabilities.md](docs/camera-capabilities.md): what was verified on a real camera.
- [docs/features.md](docs/features.md): catalogue of camera commands and their priority.
- [docs/ui-spec.md](docs/ui-spec.md): HTTP API contract and screens.
- [docs/ui-design.md](docs/ui-design.md): visual design and components of the web panel.
- [docs/glossary.md](docs/glossary.md): naming conventions used in the code.
- [docs/ghidra-notes.md](docs/ghidra-notes.md): reverse-engineering method.
- [docs/references.md](docs/references.md): related community projects and articles.

## Legal and ethical note

This is an interoperability project for hardware owned by the author. It documents observed
behaviour on the local network so that users can control their own device without a vendor
cloud. It is not affiliated with, endorsed by, or sponsored by the camera vendor. No vendor
firmware, application binaries or proprietary source code are included.

## License

MIT. See [LICENSE](LICENSE).
