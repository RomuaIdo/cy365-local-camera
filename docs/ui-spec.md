# UI Specification and HTTP API Contract

This document describes the local web control panel for a Wi-Fi IP camera and the HTTP API it uses. The panel runs entirely on the local machine and talks to the camera over the local network only.

- **Server:** `servidor.py`, listening on `127.0.0.1:8080`. Python standard library only, no external dependencies.
- **Frontend:** `static/index.html`, a single-page app written in HTML5, CSS3 and plain JavaScript. No frameworks, no CDNs, works offline.
- **Visual design:** see [ui-design.md](ui-design.md).

---

## 1. Principles

### 1.1 Credential handling

- The camera password (`pwd`) is never persisted in `localStorage`, `sessionStorage`, `IndexedDB` or cookies.
- The password is sent once, in the body of `POST /api/conectar`. The input field is cleared immediately after the request is sent.
- On the server, the password is kept only in memory in the `CameraSession` instance and is masked as `***` in any log output.

### 1.2 Protection against accidental writes

- Every write operation (`set_*`, `dev_control`, formatting) must be explicitly confirmed by the user in the UI.
- The server checks the `"confirmed": true` flag in the body of `POST /api/comando`. Write requests without this flag receive `403 Forbidden`.

### 1.3 Network isolation

- The HTTP server binds only to the loopback interface, `127.0.0.1`.
- Requests whose `Host` header is not `127.0.0.1` or `localhost` are rejected with `403 Forbidden`.
- The page loads no external resources: no CDNs, web fonts, analytics or remote links.

### 1.4 Hardware transparency

- Resources confirmed on the test camera (`check_user`, `stream`, `get_parms`, `get_whiteLight`, `set_datetime`) are marked as proven in `GET /api/recursos`.
- Resources that are unproven, or that depend on optional hardware (motorized PTZ, PIR sensor), are marked as not proven (`"proven": false`). The UI does not expose them.

### 1.5 Responsiveness

- Reference window size: **1280 x 800 px** (default desktop window).
- Minimum supported window size: **960 x 600 px**. Below 960 px wide, the navigation sidebar collapses to icons (see [ui-design.md](ui-design.md)).

---

## 2. HTTP API Contract

All JSON responses use `Content-Type: application/json; charset=utf-8`, except `/stream`, `/audio.wav` and `/api/eventos`.

Errors use the keys `error`, `detail` and `stage` (`detail` and `stage` are optional). Where useful, error responses also include a `state` object with the current session state.

### 2.1 Connection lifecycle

#### `POST /api/conectar`

Connects to the camera (LAN discovery, then P2P handshake) and logs in (`check_user`).

- **Request body:**
  ```json
  {
    "pwd": "<password>"
  }
  ```
- **Responses:**
  - `200 OK`: connected.
    ```json
    {
      "state": "connected",
      "info": {
        "admin": 1,
        "type": 2020,
        "mode": 2020,
        "checkstr": "SHIX"
      }
    }
    ```
  - `400 Bad Request`: malformed body or missing password.
    ```json
    { "error": "Password required" }
    ```
  - `401 Unauthorized`: wrong password or login rejected by the camera (`result != 0`).
    ```json
    {
      "error": "Incorrect password",
      "detail": "result=13 (cmd=100)",
      "stage": "login",
      "state": {
        "state": "error",
        "reason": "Incorrect password",
        "video_on": false,
        "audio_on": false,
        "last_error": "Incorrect password: result=13 (cmd=100)"
      }
    }
    ```
  - `409 Conflict`: a session is already connected or connecting.
    ```json
    { "error": "Session already connected" }
    ```
  - `504 Gateway Timeout`: the camera did not answer on the local network.
    ```json
    {
      "error": "Camera did not respond on the local network",
      "detail": "timeout",
      "stage": "lansearch",
      "state": {
        "state": "error",
        "reason": "Camera did not respond on the local network",
        "video_on": false,
        "audio_on": false,
        "last_error": "Camera did not respond on the local network: timeout"
      }
    }
    ```

#### `POST /api/desconectar`

Ends the P2P session, closes the video and audio workers, and clears the password from memory.

- **Request body:** `{}`
- **Response `200 OK`:**
  ```json
  { "state": "disconnected" }
  ```

#### `GET /api/estado`

Returns the current session state and media flags.

- **Response `200 OK`:**
  ```json
  {
    "state": "connected",
    "reason": null,
    "video_on": true,
    "audio_on": false,
    "last_error": null
  }
  ```
- Possible values of `state`: `"disconnected"`, `"connecting"`, `"connected"`, `"error"`.

#### `GET /api/eventos` (Server-Sent Events)

Real-time event stream (`Content-Type: text/event-stream`). The UI uses it to stay in sync without continuous polling.

- **Event emitted:**
  ```
  event: state
  data: {"state": "connected", "reason": null, "video_on": true, "audio_on": false, "last_error": null}
  ```

### 2.2 Video and audio control

#### `POST /api/video`

Starts or stops the MJPEG video stream (channel 1).

- **Request body:**
  ```json
  { "on": true }
  ```
- **Responses:**
  - `200 OK`: `{ "video_on": true }`
  - `401 Unauthorized`: session not connected.

#### `POST /api/audio`

Starts or stops the audio stream (channel 2, G.711 A-law or IMA ADPCM from the camera).

- **Request body:**
  ```json
  { "on": true }
  ```
- **Responses:**
  - `200 OK`: `{ "audio_on": true }`
  - `401 Unauthorized`: session not connected.

#### `GET /stream` (MJPEG)

Continuous `multipart/x-mixed-replace` stream of JPEG frames, consumed by the `<img>` element in the page.

- **Response header:** `Content-Type: multipart/x-mixed-replace; boundary=frame`
- **When video is off:** `204 No Content`. The page shows its own "Video paused" overlay.

#### `GET /audio.wav` (live audio)

Endless WAV stream of PCM audio decoded from the camera's IMA ADPCM frames.

- **Format:** PCM, 16-bit signed, mono, 8000 Hz.
- **Header:** the RIFF size and the `data` chunk size are both set to `0xFFFFFFFF`, which marks the length as unknown. The server keeps sending samples for as long as audio is enabled.
- **Response header:** `Content-Type: audio/wav`
- **When audio is off:** `204 No Content`.
- **Playback in the browser:** Chrome cannot play an endless WAV directly from an `<audio src>` attribute. The page therefore fetches `/audio.wav`, decodes the PCM with the Web Audio API, routes it into a `MediaStreamAudioDestinationNode`, and plays the resulting `MediaStream` through an `<audio>` element (`srcObject`). Volume and mute are applied to the `<audio>` element.

### 2.3 Resources and generic commands

#### `GET /api/recursos`

Lists the commands that the backend permits, based on the priority 1 and 2 command set.

- **Response `200 OK`:**
  ```json
  {
    "resources": [
      { "id": "check_user", "cmd": 100, "name": "Login and authentication", "priority": 1, "proven": true, "write": false },
      { "id": "stream", "cmd": 300, "name": "Live video and audio", "priority": 1, "proven": true, "write": true },
      { "id": "get_wifi", "cmd": 112, "name": "Wi-Fi query", "priority": 1, "proven": false, "write": false },
      { "id": "scan_wifi", "cmd": 113, "name": "Wi-Fi network scan", "priority": 1, "proven": false, "write": false },
      { "id": "set_wifi", "cmd": 114, "name": "Wi-Fi configuration", "priority": 1, "proven": false, "write": true },
      { "id": "get_parms", "cmd": 101, "name": "Telemetry and battery", "priority": 2, "proven": true, "write": false },
      { "id": "get_whiteLight", "cmd": 305, "name": "White light status", "priority": 2, "proven": true, "write": false },
      { "id": "set_whiteLight", "cmd": 304, "name": "White light control", "priority": 2, "proven": false, "write": true },
      { "id": "set_datetime", "cmd": 108, "name": "Clock synchronization", "priority": 1, "proven": true, "write": true }
    ]
  }
  ```

#### `POST /api/comando`

Sends a JSON command to the camera over channel 0 (`0xD0`).

- **Request body (read):**
  ```json
  {
    "pro": "get_wifi",
    "cmd": 112,
    "fields": {}
  }
  ```
- **Request body (write, requires `"confirmed": true`):**
  ```json
  {
    "pro": "set_whiteLight",
    "cmd": 304,
    "fields": { "status": 1 },
    "confirmed": true
  }
  ```
- **Responses:**
  - `200 OK`: the camera's JSON response, wrapped.
    ```json
    {
      "success": true,
      "response": { "cmd": 304, "result": 0 }
    }
    ```
  - `403 Forbidden`: a write command (`set_*`, `dev_control`, `format_*`) without `"confirmed": true`.
    ```json
    { "error": "Write operation requires explicit confirmation (confirmed=true)" }
    ```
  - `403 Forbidden`: the command is not in the permitted resource list.
    ```json
    { "error": "Command not allowed or not supported" }
    ```
  - `504 Gateway Timeout`: no reply from the camera within 5 seconds.
    ```json
    { "error": "Camera did not reply within the timeout", "detail": "timeout" }
    ```

#### Device endpoints used by the Controls and Information screens

| Method and path | Purpose | Request body | Response (`200 OK`) |
|:---|:---|:---|:---|
| `GET /api/info` | Telemetry from `get_parms` (cmd 101) | none | `{ "battery": 100, "charging": true, "firmware": "CYCAM_T99_v32_0226", "time": 1792027589, "led_status": 1 }` |
| `POST /api/indicador` | Blue status LED (`dev_control` cmd 102, parameter `lamp`) | `{ "on": true }` | `{ "indicator": true, "confirmed": true }` |
| `POST /api/infravermelho` | Infrared filter mode (`dev_control` cmd 102, parameter `icut`) | `{ "mode": 0 \| 1 \| 2 }` | `{ "mode": 2, "confirmed": true }` |
| `GET /api/rede` | Wi-Fi SSID and operating mode from `get_wifi` (cmd 112) | none | `{ "ssid": "example-network", "conmode": 1 }` |

Notes:

- `time` is a Unix epoch timestamp in seconds.
- `led_status` and `indicator` use `1` / `true` for on and `0` / `false` for off.
- `mode` values: `0` = off, `1` = on, `2` = automatic.
- `conmode` values: `1` = station (infrastructure LAN), `0` = access point (AP) mode.
- Errors: `400 Bad Request` for a missing `on` field or a `mode` outside `[0, 1, 2]`; `401 Unauthorized` when the session is not connected; `504 Gateway Timeout` when the camera does not answer in time.

---

## 3. Screens

The page has a fixed window frame with a title bar, a menu bar, a left navigation sidebar, a central workspace and a status bar. The workspace shows one of five screens at a time.

```
+---------------------------------------------------------------------------------------------+
| [camera icon] Camera CY365 - Control Panel           Status: [o Connected]  [_][ ][X]       | title bar, 48 px
+---------------------------------------------------------------------------------------------+
|  File    Camera    View    Help                                                             | menu bar, 26 px
+-------------------+-------------------------------------------------------------------------+
| Video             | Central workspace (group-box cards)                                     |
| Controls          |                                                                         |
| Information       |                                                                         |
| Network           |                                                                         |
| About             |                                                                         |
|                   |                                                                         |
| sidebar, 200 px   |                                                                         |
+-------------------+-------------------------------------------------------------------------+
| Ready | Camera: CYCAM_T99 | 192.168.1.x:32108 | Battery: 100% (charging) | Audio off         | status bar, 24 px
+---------------------------------------------------------------------------------------------+
```

### 3.1 Connection dialog (modal)

Shown when the session is `disconnected` or `error`, and opened from the **Camera > Connect...** menu item.

- **Purpose:** authenticate with the camera without storing the password in the browser.
- **Components:**
  - Title: "Connect to camera".
  - Password field: `<input type="password" id="input-password" placeholder="Camera password">`.
  - Connect button: `<button id="btn-connect" class="btn primary">Connect</button>`.
  - Error area: hidden by default. Shows the reason returned by the server when the session is in `error` (for example "Incorrect password: result=13" or "Camera did not respond on the local network").
- **Actions:**
  - Clicking Connect disables the button, shows a progress message, and sends `POST /api/conectar` with `{ "pwd": ... }`.
  - Immediately after the request is sent, the field is cleared.

### 3.2 Video screen (`Ctrl+1`)

- **Purpose:** show the live stream and provide playback, snapshot and audio controls.
- **Components:**
  - **Live view:** `<img id="stream-image" src="/stream" alt="Video stream">` inside a video frame.
  - **Status overlay:** `Live` badge (green) when video is on, `Paused` badge (amber) when it is off.
  - **Paused overlay:** shown over the frame when video is off, with the text "Video paused. Click 'Resume video' to continue."
  - **Pause / Resume video button:** sends `POST /api/video` with `{ "on": false }` or `{ "on": true }`. The label switches between "Pause video" and "Resume video".
  - **Photo button:** copies the current frame into a hidden `<canvas>` and triggers a browser download named `foto_YYYYMMDD_HHMMSS.jpg`. A toast reads "Frame captured and saved."
  - **Full screen button:** requests full-screen mode for the video card with `requestFullscreen()`.
  - **Audio switch:** labelled "Audio". Sends `POST /api/audio` with `{ "on": true }` or `{ "on": false }`. When on, the page starts the live WAV playback described in section 2.2. Status text reads "Audio on" or "Audio off".
  - **Mute button:** mutes or unmutes the local `<audio>` element. It does not change the camera.
  - **Reconnect audio button:** shown only when the audio playback has failed. Restarts the playback.
  - **Player volume slider:** sets the local `<audio>` element volume from 0 to 100% (default 75%). It does not send any command to the camera. The current value is shown next to the slider.

### 3.3 Controls screen (`Ctrl+2`)

Direct control of the camera's onboard hardware.

- **Status LED:**
  - Label: "Indicator (blue LED)", with the note "Status LED on the back of the camera."
  - Toggle switch. Sends `POST /api/indicador` with `{ "on": true }` or `{ "on": false }`.
  - Initial state is read from `GET /api/info` (`led_status`).
- **Infrared night vision:**
  - Label: "Infrared (night vision)".
  - Dropdown with three options: `Off` (`0`), `On` (`1`), `Automatic` (`2`).
  - Sends `POST /api/infravermelho` with `{ "mode": 0 | 1 | 2 }`.
  - Caption: "Changing the infrared filter affects the image on the Video screen."

### 3.4 Information screen (`Ctrl+3`)

Device telemetry.

- **Battery level:** progress bar and percentage, from `battery`.
- **USB charging:** "Yes (connected to power)" when `charging` is `true`, otherwise "No (running on battery)".
- **Firmware version:** monospace text, for example `CYCAM_T99_v32_0226`.
- **Camera clock:** date and time formatted from the Unix epoch value in `time`.
- **Status light:** whether the blue LED is currently on, from `led_status`.
- **Refresh:**
  - "Refresh now" button triggers an immediate `GET /api/info`.
  - While this screen is visible, the page polls `GET /api/info` every 10 seconds.
  - "Last update" text shows the time since the last successful read.
- **Error area:** shows the error message if the request fails.

### 3.5 Network screen (`Ctrl+4`)

Read-only network information. The screen has no configuration controls.

- **Connected Wi-Fi network (SSID):** value of `ssid` from `GET /api/rede`.
- **Operating mode:** translation of `conmode`:
  - `1`: "Station (infrastructure LAN)"
  - `0`: "Access point (AP mode)"
- **Refresh button:** triggers `GET /api/rede` again.
- **Notice:** a muted note that this screen is read-only, because changing network settings can disconnect the camera.

Wi-Fi configuration (scan and change of the camera's network) is not implemented in the page. The generic command endpoint `POST /api/comando` accepts `set_wifi` only as a confirmed write, as described in section 2.3.

### 3.6 About screen (`Ctrl+5`)

- **Title:** "About"
- **Text:** "Local control panel for a Wi-Fi camera on this network."

---

## 4. Interface State Matrix

| Session state (`state`) | Enabled controls | Main message | Indicator |
|:---|:---|:---|:---|
| `disconnected` | Connection dialog only | "Ready to connect to the camera." | Grey circle, "Disconnected" |
| `connecting` | None (inputs disabled) | "Discovering device and authenticating..." | Amber dot, "Connecting" |
| `connected` | All screens and controls | "Camera connected." | Green dot, "Connected" |
| `error` | Connection dialog re-enabled | "Error: <reason returned by the server>" | Red circle, "Error" |
| Video paused (`video_on: false`) | Controls active, video area paused | "Video paused. Click 'Resume video' to continue." | Blue badge, "Paused" |

---

## 5. Keyboard Shortcuts

| Shortcut | Action |
|:---|:---|
| `Ctrl+1` to `Ctrl+5` | Switch to Video, Controls, Information, Network or About |
| `Space` | Pause or resume the video (when the Video screen is active and no text field has focus) |
| `Escape` | Leave full-screen mode or close the dialog |

---

## 6. Layout and CSS Notes

- Colors are defined as CSS custom properties. Dark theme is the default; a light theme is selectable from the View menu.
- System font stack only, no web fonts.
- At widths below 960 px, the sidebar collapses to icons with tooltips, and the workspace cards reflow.
- Full dimensions, tokens and component rules are in [ui-design.md](ui-design.md).
