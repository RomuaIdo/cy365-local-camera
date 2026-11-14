# UI Design Specification (Desktop-Style Fusion / Breeze Theme)

Visual design specification for the local web control panel for a Wi-Fi IP camera. The page imitates the look of a native desktop application (Qt6 Fusion / KDE Breeze styles) inside a browser window. It has no external dependencies: no fonts, no CDNs, no third-party scripts.

- **Target:** a local page served at `http://127.0.0.1:8080/`.
- **Look and feel:** a desktop-style window with title bar, menu bar, sidebar navigation, group-box cards, standard widgets and a status bar.
- **Default theme:** dark (Fusion / Breeze). A light Fusion theme is available from the View menu.
- **Language:** all user-visible text is in English. JSON keys and code identifiers are in English as well.
- **Behavior and API contract:** see [ui-spec.md](ui-spec.md).

---

## 1. Design Tokens and Theme Variables

Colors, sizes and shadows are defined as CSS custom properties on `:root`. The dark palette follows the Fusion / Breeze Dark look; the light palette follows Fusion Light.

```css
/* Base system font stack (no external network requests) */
:root {
  --qt-font-family: system-ui, -apple-system, "Segoe UI", Roboto, Noto, Ubuntu, "Helvetica Neue", Arial, sans-serif;
  --qt-font-mono: "JetBrains Mono", "Cascadia Code", "Fira Code", Consolas, Menlo, Monaco, monospace;

  /* Metrics */
  --qt-font-size-base: 13px;
  --qt-font-size-sm: 11px;
  --qt-font-size-lg: 15px;
  --qt-font-size-title: 18px;
  --qt-line-height: 1.4;
  --qt-radius-sm: 3px;
  --qt-radius-base: 5px;
  --qt-radius-lg: 8px;

  /* Focus outline for keyboard navigation */
  --qt-focus-ring: 2px solid var(--qt-accent);
  --qt-focus-offset: 1px;
}

/* Dark theme (default) - Fusion / Breeze Dark */
:root, [data-theme="dark"] {
  --qt-window-bg: #1e1e1e;          /* Main window background */
  --qt-window-title-bg: #2d2d2d;    /* Title bar background */
  --qt-menubar-bg: #2d2d2d;         /* Menu bar background */
  --qt-sidebar-bg: #252526;         /* Left sidebar background */
  --qt-sidebar-active: #37373d;     /* Active sidebar item */
  --qt-card-bg: #252526;            /* Group-box container background */
  --qt-card-header: #2d2d30;        /* Group-box title fill */
  --qt-statusbar-bg: #2d2d2d;       /* Status bar */

  --qt-control-bg: #333333;         /* Button and input surface */
  --qt-control-bg-hover: #3e3e42;   /* Hover state */
  --qt-control-bg-pressed: #222222; /* Pressed state */
  --qt-control-border: #474747;     /* Standard widget border */
  --qt-control-border-hover: #606060;

  --qt-text-primary: #e0e0e0;       /* High-contrast text */
  --qt-text-secondary: #aaaaaa;     /* Subtitles, units, disabled text */
  --qt-text-muted: #777777;         /* Footers, shortcuts */

  --qt-accent: #2a82da;             /* Fusion active blue */
  --qt-accent-hover: #3a92ea;
  --qt-accent-pressed: #1a72ca;
  --qt-accent-text: #ffffff;

  --qt-success: #2ea44f;            /* Connected / live green */
  --qt-warning: #e3a008;            /* Caution / paused yellow */
  --qt-danger: #e04545;             /* Error / disconnected red */

  --qt-shadow-subtle: 0 1px 3px rgba(0, 0, 0, 0.4);
  --qt-shadow-modal: 0 8px 24px rgba(0, 0, 0, 0.6);
}

/* Light theme (alternative) - Fusion Light */
[data-theme="light"] {
  --qt-window-bg: #f0f0f0;
  --qt-window-title-bg: #e6e6e6;
  --qt-menubar-bg: #e6e6e6;
  --qt-sidebar-bg: #e8e8e8;
  --qt-sidebar-active: #d0d0d0;
  --qt-card-bg: #ffffff;
  --qt-card-header: #f5f5f5;
  --qt-statusbar-bg: #e6e6e6;

  --qt-control-bg: #f6f6f6;
  --qt-control-bg-hover: #ffffff;
  --qt-control-bg-pressed: #e2e2e2;
  --qt-control-border: #b8b8b8;
  --qt-control-border-hover: #888888;

  --qt-text-primary: #1a1a1a;
  --qt-text-secondary: #555555;
  --qt-text-muted: #888888;

  --qt-accent: #2a82da;
  --qt-accent-hover: #1e70c0;
  --qt-accent-pressed: #155a9c;
  --qt-accent-text: #ffffff;

  --qt-success: #28a745;
  --qt-warning: #d97706;
  --qt-danger: #cb2431;

  --qt-shadow-subtle: 0 1px 3px rgba(0, 0, 0, 0.1);
  --qt-shadow-modal: 0 8px 24px rgba(0, 0, 0, 0.25);
}
```

---

## 2. Typography

- **Base size:** `13px`.
- **Font stack:** system font stack only. Web fonts are never loaded.
- **Hierarchy:**
  - Title bar title: `14px`, medium weight (`500`).
  - Group-box legend: `13px`, bold (`600`), accent or primary text color.
  - Body and widget labels: `13px`, regular (`400`).
  - Secondary and meta text: `11px`, regular (`400`), muted color.
  - Status bar and keyboard hints: `11px`, regular (`400`).
  - Telemetry and numeric values: `13px`, monospace font family, for aligned digits.

---

## 3. Window and Layout

The interface reproduces a single application window inside the browser viewport:

```
+---------------------------------------------------------------------------------------------+
| [icon] Camera CY365 - Control Panel                       Status: [Connected]   [_][ ][X]   | 48 px
+---------------------------------------------------------------------------------------------+
|  File       Camera     View     Help                                                        | 26 px
+-------------------+-------------------------------------------------------------------------+
| Video             | Central workspace (group-box cards)                                     |
| Controls          |                                                                         |
| Information       |                                                                         |
| Network           |                                                                         |
| About             |                                                                         |
|                   |                                                                         |
| sidebar 200 px    |                                                                         |
+-------------------+-------------------------------------------------------------------------+
| Ready | Camera: CYCAM_T99 | 192.168.1.x:32108 | Battery: 100% (charging) | 8000 Hz      | 24 px
+---------------------------------------------------------------------------------------------+
```

### 3.1 Dimensions and zones

1. **Title bar (height 48 px):**
   - Left: application icon and title "Camera CY365 - Control Panel".
   - Right: connection status badge (pill label) and window control decorations.
2. **Menu bar (height 26 px):**
   - Items: `File`, `Camera`, `View`, `Help`.
   - Native menu appearance with hover highlight and keyboard accelerators (`Alt+F`, `Alt+C`, `Alt+V`, `Alt+H`).
3. **Left navigation sidebar (width 200 px):**
   - Fixed column with vertical tab items, matching a Qt list widget or vertical toolbar.
   - Five items, each with an icon and a label:
     1. Video (`Ctrl+1`)
     2. Controls (`Ctrl+2`)
     3. Information (`Ctrl+3`)
     4. Network (`Ctrl+4`)
     5. About (`Ctrl+5`)
4. **Central workspace (fluid):**
   - Contains the active screen, built from group-box cards.
   - Scrolls vertically if content overflows; the title bar, menu bar and sidebar stay fixed.
5. **Status bar (height 24 px):**
   - Fixed at the bottom edge.
   - Segmented panels: general message, camera model, camera address and port, battery, audio state.

---

## 4. Component Specifications

### 4.1 Push button

- **Visual:** rectangular beveled button with a subtle inset border and 3 px corner radius.
- **Variants:**
  - Standard: grey control background, dark border.
  - Primary: Fusion blue background (`--qt-accent`), white text.
  - Danger: red background (`--qt-danger`), white text.
- **States:**
  - Normal: `background: var(--qt-control-bg); border: 1px solid var(--qt-control-border);`
  - Hover: `background: var(--qt-control-bg-hover); border-color: var(--qt-control-border-hover);`
  - Pressed: `background: var(--qt-control-bg-pressed); box-shadow: inset 0 1px 2px rgba(0,0,0,0.3);`
  - Disabled: `opacity: 0.5; cursor: not-allowed;`
  - Focus: `:focus-visible { outline: var(--qt-focus-ring); outline-offset: var(--qt-focus-offset); }`

### 4.2 Toggle switch (checkbox styled as a switch)

- **Visual:** pill-shaped track with a sliding round knob, resembling a hardware toggle.
- **Track:** 38 px wide, 20 px high, 10 px radius.
- **Thumb:** 16 px diameter, white, subtle drop shadow.
- **States:**
  - Off: track `#444444` (dark theme) or `#cccccc` (light theme). Thumb at the left, 2 px margin.
  - On: track `var(--qt-accent)`. Thumb moved 18 px to the right.
  - Hover: track 10% brighter.
  - Focus: focus ring around the track.

### 4.3 Slider

- **Visual:** horizontal slider for the player volume.
- **Groove:** 4 px high, background `--qt-control-border`, 2 px radius.
- **Handle:** 14 px wide, 18 px high, rounded rectangle (2 px radius), 1 px border `--qt-control-border`, background `--qt-control-bg-hover`.
- **States:** while grabbed, the handle is highlighted with `--qt-accent`.

### 4.4 Drop-down list

- **Visual:** rectangular button with a downward chevron on the right.
- **Size:** 28 px high, padding 4px 10px, 3 px radius.
- **Popup list:** 1 px border, background `--qt-card-bg`. Hovered item uses `--qt-accent` background with white text.

### 4.5 Group box (card)

- **Visual:** card with a 1 px solid border (`--qt-control-border`) and 5 px radius.
- **Legend / title:** bold 13 px label over the top border, indented 12 px, with a background that cuts the border line.
- **Padding:** 16 px inside the card.

### 4.6 Status chip (pill label)

- **Visual:** compact rounded pill (10 px radius, padding 2px 8px, 11 px bold text). A small coloured dot may precede the text.
- **Types:**
  - Live / Connected: background `rgba(46, 164, 79, 0.2)`, text `--qt-success`.
  - Paused: background `rgba(227, 160, 8, 0.2)`, text `--qt-warning`.
  - Disconnected: background `rgba(224, 69, 69, 0.2)`, text `--qt-danger`.

### 4.7 Toast notification

- **Visual:** floating rectangle in the top-right corner of the window.
- **Timing:** shown for 3.5 seconds, with a fade-in and slide-down transition.
- **Style:** background `--qt-menubar-bg`, 1 px border `--qt-accent`, shadow `--qt-shadow-modal`.

### 4.8 Confirmation dialog

- **Visual:** centred modal window with a title bar, a warning or question icon, a message and a button box (`Confirm` / `Cancel`).
- **Backdrop:** translucent dark scrim (`rgba(0,0,0,0.5)`).
- **Use:** any write operation that is not already confirmed by the control itself.

---

## 5. Screen Layouts

The page has five screens. Wi-Fi configuration, SD card recording, camera alarm, camera volume control, white light reflector and PTZ controls are not part of the current screens.

### Screen 1: Video (`Ctrl+1`)

```
+------------------------------------------------------------------------------------+
| Live transmission                                                                  |
|   +----------------------------------------------------------------------------+   |
|   |                       <img id="stream-image" src="/stream">                |   |
|   |                                                    [Live] (overlay)        |   |
|   +----------------------------------------------------------------------------+   |
|   [ Pause video ]   [ Photo ]   [ Full screen ]                                    |
|   ------------------------------------------------------------------------------   |
|   Audio:  [switch: Audio (off)]   Player volume: [====O=======] 75%               |
+------------------------------------------------------------------------------------+
```

- **Live view:** `<img id="stream-image" src="/stream" alt="Video stream">`, aspect ratio of the sensor (GC0311).
- **Overlay badge:** top-left corner, `Live` (green) or `Paused` (amber).
- **Pause / Resume video:** pauses or resumes the stream. When paused, the frame is replaced by a dark area with the text "Video paused. Click 'Resume video' to continue."
- **Photo:** saves the current frame as `foto_YYYYMMDD_HHMMSS.jpg` and shows the toast "Frame captured and saved."
- **Full screen:** requests HTML5 full-screen mode for the video card.
- **Audio switch:** labelled "Audio" with the sublabel "Microphone audio". Plays the live audio stream when on.
- **Player volume slider:** 0 to 100% for the local audio player only, with the current value shown next to it. It does not change the camera.

### Screen 2: Controls (`Ctrl+2`)

```
+------------------------------------------------------------------------------------+
| Actuators and lighting                                                             |
|   Indicator (blue LED):   [switch: On]                                             |
|   Status LED on the back of the camera.                                            |
|   ------------------------------------------------------------------------------   |
|   Infrared (night vision):                                                         |
|   Mode: [ Automatic            v ]    (Off / On / Automatic)                       |
|   Changing the infrared filter affects the image on the Video screen.              |
+------------------------------------------------------------------------------------+
```

- **Status LED:** toggle switch, label "Indicator (blue LED)", subtitle "Status LED on the back of the camera." Initial state comes from the device information.
- **Infrared filter:** drop-down with `Off`, `On` and `Automatic`. Caption: "Changing the infrared filter affects the image on the Video screen."

### Screen 3: Information (`Ctrl+3`)

```
+------------------------------------------------------------------------------------+
| Device status                                                                      |
|   Battery level:        [####################] 100%                                |
|   USB charging:         Yes (connected to power)                                   |
|   Firmware version:     CYCAM_T99_v32_0226                                         |
|   Camera clock:         2026-10-17 12:14:00 (UTC)                                  |
|   Status LED:           On                                                         |
|   ------------------------------------------------------------------------------   |
|   [ Refresh now ]   Last update: 3 seconds ago                                     |
|   Automatic refresh every 10 seconds while this screen is visible.                 |
+------------------------------------------------------------------------------------+
```

- **Battery:** progress bar and numeric value.
- **USB charging:** "Yes (connected to power)" or "No (running on battery)".
- **Firmware string:** monospace font.
- **Camera clock:** date and time formatted from the Unix epoch value.
- **Refresh:** "Refresh now" button, plus an automatic refresh every 10 seconds while this screen is visible.

### Screen 4: Network (`Ctrl+4`)

```
+------------------------------------------------------------------------------------+
| Wi-Fi parameters                                                                   |
|   Connected Wi-Fi network (SSID):    example-network                               |
|   Operating mode:                    Station (infrastructure LAN)                  |
|   ------------------------------------------------------------------------------   |
|   [lock] This screen is read-only.                                                 |
|          Network settings should stay unchanged to avoid losing the connection.    |
+------------------------------------------------------------------------------------+
```

- **SSID:** value of `ssid`.
- **Operating mode:** `1` shows "Station (infrastructure LAN)", `0` shows "Access point (AP mode)".
- **Notice:** a muted information badge explaining that the screen is read-only, to protect the network link.

### Screen 5: About (`Ctrl+5`)

```
+------------------------------------------------------------------------------------+
| About                                                                              |
|   Local control panel for a Wi-Fi camera on this network.                          |
|                                                                                    |
|   The application talks directly to the camera on the local network (LAN).         |
|   It does not connect to cloud servers or third-party services.                    |
|                                                                                    |
|   Technologies: Python 3 standard-library server, plain HTML5/CSS3 and JavaScript, |
|   G.711 A-law / IMA ADPCM audio decoding, Web Audio API playback.                  |
+------------------------------------------------------------------------------------+
```

---

## 6. Responsiveness

1. **Reference window:** `1280 x 800 px`.
2. **Minimum window:** `960 x 600 px`.
3. **Breakpoint below 960 px:**
   - The sidebar collapses from 200 px to an icon-only column (56 px).
   - Sidebar labels are hidden (`display: none`) and the icons remain.
   - Each icon has a tooltip with its label.
   - Cards reflow fluidly without breaking the widget layout.

---

## 7. Accessibility and Keyboard Navigation

1. **Contrast:** text and interactive controls meet WCAG 2.1 AA: at least 4.5:1 for regular text and 3:1 for large text and UI components.
2. **Visible focus:** every interactive control uses `:focus-visible` with a 2 px solid Fusion blue ring (`var(--qt-accent)`).
3. **Keyboard shortcuts:**
   - `Ctrl+1` to `Ctrl+5`: switch to Video, Controls, Information, Network or About.
   - `Space`: pause or resume the video (when the Video screen is active and no text field has focus).
   - `Escape`: leave full-screen mode or close a dialog.
4. **Status updates:** the connection badge and the status bar use `role="status"` and `aria-live="polite"`.

---

## 8. Security and Privacy

1. **No password storage:**
   - The password is never written to `window.localStorage`, `window.sessionStorage`, `document.cookie` or IndexedDB.
   - The password field is cleared as soon as the form is submitted.
2. **Local-only access:**
   - All requests go to `127.0.0.1:8080`.
   - The server rejects requests whose `Host` header is not `127.0.0.1` or `localhost`.
   - The page loads no third-party scripts, stylesheets, trackers or remote fonts.
3. **Write confirmation:** write operations require explicit confirmation, enforced by the server through the `confirmed` flag (see [ui-spec.md](ui-spec.md), section 2.3).
