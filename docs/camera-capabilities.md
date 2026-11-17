# Camera Capabilities (read-only probe, 2026-10-15)

Source: read-only probe of the camera on the local network. Login returned result=0; the probe sent 11 read-only commands. The source notes list 10 of them (see the note in the first section below).

Probe method: each read command was sent after login and the reply was recorded. A command with no reply within 5 s is reported as "no response". Write commands were only sent in the separate tests described further below, after confirmation on the camera.

## Commands that responded (proven)

| Command | Cmd | Useful data |
|---|---|---|
| get_wifi | 112 | Current network SSID (omitted here), conmode=1 (station) |
| get_parms | 101 | Firmware CYCAM_T99_v32_0226, battery 100%, charging=1, sensor, icut, bright, contrast |
| get_whiteLight | 305 | status=0. No white light is visible on the camera; the field name may refer to something else (see the write tests) |
| get_sd | 110 | sdstatu=0, recMode=1. **The camera has NO card slot (confirmed on the device)**: the reply is generic and does not indicate a card |

Note: the probe reports 11 read-only commands, but only 10 are named in the source notes (4 responded, 6 gave no response). The eleventh is not identified in the source notes.

## No response within 5 s (likely not supported by this camera; NOT proven)

get_product (200), get_vol (134), get_alarm (107), get_record_param (199), get_record_day (205), get_record_list (206).

Interpretation: no reply means the command is not implemented or not applicable. This can only be confirmed with a retry using a longer timeout.

## Conclusions from the physical device (no SD slot)

- Recording to a memory card does NOT exist on this camera. get_sd, get_record_param, get_record_day and get_record_list do not apply. They should be removed from the application.
- The silence of get_record_* is consistent with the absence of storage (it is not only a bug on our side). [HYPOTHESIS, but consistent]
- set_sd (formatting) should not be offered.

## Not yet tested (write commands, require confirmation before running)

set_wifi (114), set_vol (135), set_alarm (108), set_sd (110, write), set_datetime (126), talk (300 / 129 / 130).

Note: set_whiteLight (304) and live audio (stream with audio=1, channel 2) were tested later; see the sections below.

## Write tests performed

- **set_whiteLight (304), 2026-10-15: the command was accepted (result=0) and the read-back matches, but NO physical effect was observed.** Photos of the camera show no white light on the front of the camera; there is only a blue LED on the back that blinks with the connection status and can be turned off from the app. It is not known whether set_whiteLight controls this LED, so the "white light" label may be wrong.
- Test sequence: get 305 status=0, then set 304 status=1 (result=0), then get status=1, then set status=0 (result=0), then get status=0. The original state was restored. Script: `code/teste_escrita_luz.py` (requires `--confirmar`).

## Discovery: blue LED = field "lamp" (2026-10-15)

- The app calls the LED "Indicator light" (strings: playview_zsd; layout popup_playmore_funtion.xml, switch sv_zsd).
- Code: NDDoubleCameraLiveActivity.java:1184-1190 and :1711-1718 send `CameraControl(..., "lamp", 1|0)`, producing the JSON `{"pro":"dev_control","cmd":102,"user":...,"pwd":...,"lamp":1|0}`.
- Matching read: get_parms (101) returns `"lamp"`. In the probe of the day, lamp=1 (indicator on, consistent with the blinking LED).
- set_whiteLight (304) is NOT the blue LED. Likely: a night-vision setting, or nothing. [HYPOTHESIS] A hypothesis, consistent with the icut code path (IR filter, day/night, dev_control "icut" 0/1/2), still to be verified.
- Other dev_control fields (CameraControl) found in the code: icut (0/1/2), contrast, bright, rotmir, clockScreen, lamp. Dangerous; NOT to be tested without confirmation: reboot (1), reset (1), upgrade (1).
- **dev_control cmd 102 with lamp (blue "Indicator light"): read-back confirmed.** Original lamp=1, then lamp=0 was sent, get_parms showed lamp=0, then lamp=1 was restored and get_parms showed lamp=1. Script: `code/teste_escrita_lamp.py`. The LED was confirmed to turn off and come back on, on the camera.
- **Indicator (blue LED) CONFIRMED physically on the camera:** it turned off with lamp=0 and back on with lamp=1. Feature ready for the app: dev_control cmd 102 `{"lamp": 0|1}`; state is read from get_parms.

## Night-vision menu mapped to commands (from the code and the app texts)

| Menu option (app) | App text (strings) | Command | Value |
|---|---|---|---|
| Infrared Switch (title) | - | - | - |
| Infrared close | icut_close (icut0) | dev_control 102 `icut` | 0 |
| Infrared open ("Infrared on") | icut_open (icut1) | dev_control 102 `icut` | 1 |
| Infrared auto ("infrared automatic") | icut_auto (icut2) | dev_control 102 `icut` | 2 |
| Light open ("white light on") | n_play_li_open (icut3) | set_whiteLight 304 `status` | 1 |
| Light close ("baiguanguan", meaning turn off) | n_play_li_close (icut4) | set_whiteLight 304 `status` | 0 |
| Light auto ("white light automatic") | n_play_li_auto (icut5) | set_whiteLight 304 `status` | 2 |

Sources: NDDoubleCameraLiveActivity.java:1196-1230 (icut0..2), NDNCameraLiveActivity.java:379-388 (whiteLightStatus 1 maps to icut3, 2 to icut5, 0 to icut4).

Observation: "Light" is the same resource tested as set_whiteLight. It is not a visible LED. [HYPOTHESIS] It may be the infrared illuminator (invisible to the naked eye), which would explain why no effect was seen. To test without looking at the camera: measure the average brightness of the JPEG frames with status 1 versus 0 in a dark scene.

## Night-vision test by frame measurement (2026-10-15, dark bag)

Script: `code/teste_visao_noturna.py`. Original values restored: icut=1, light=1, lamp=1.

| Phase | Frames | Mean brightness | Mean saturation |
|---|---|---|---|
| base (icut=1, light=1) | 3 | 121.1 | 0.0 |
| icut=0 | 12 | 55.3 | 1.4 |
| icut=1 | 4 | 102.8 | 0.3 |
| icut=2 (auto) | 5 | 118.6 | 0.0 |
| light=0 | 6 | 117.5 | 0.0 |
| light=1 | 7 | 116.0 | 0.0 |

Reading: icut changes the brightness clearly (icut=0 is the darkest and the only one with some color). Light 0 versus 1: difference of about 1.5, within noise; not measurable in this scene.

Limitations: few frames per phase (3-12), short wait window, a single repetition. Not sufficient to claim a light effect without repetition.

## Conclusions (confirmed on the camera)

- **Infrared (icut): WORKS.** The mode change is visible in the image (measurement and app).
- **White light (set_whiteLight): NO VISIBLE EFFECT.** Neither in the app nor in the numbers. Treat as an unsupported resource on this camera. [HYPOTHESIS] Likely: the firmware accepts the command, but the camera has no such illuminator.
- **Single session:** while one client (our test) controls the camera, the app cannot open the video. The new application must be the only active client: it should warn if another session already exists and offer to disconnect.

## Live audio CONFIRMED (2026-10-15)

- Codec IMA ADPCM (high nibble first, state reset per frame). Decoding in `code/teste_audio.py`.
- 20 s test: 494 frames, 19.76 s, RMS 338, peak 4094. Listened on the camera: speech and ambient sounds were correct, volume low (microphone sensitivity is low, adjustable).
- Command: stream cmd 111 with `"audio":1`; data on DRW channel 2.
- Microphone: the camera records audio. Sending audio to the camera (channel 3 / start_talk) has not been tested.

## Wi-Fi: write test with the SAME network (2026-10-15)

- Script: `code/teste_escrita_wifi.py` (`--enc 3` = WPA2-PSK, network using WPA/WPA2-Personal; password requested without echo).
- Scan (scan_wifi, reply in `data`): reports ALL networks as encryption 0 and signal 100. NOT reliable for configuration.
- set_wifi sent with the same SSID and password: NO reply within 8 s (expected if the camera restarts its network interface).
- After 60 s the camera was reachable again on the local network, with the same SSID and conmode=1.
- Limitation: it is not known whether the command was applied or ignored. The camera does not drop off the network with the correct configuration; acceptance of the command is not proven.
- Recovery: physical reset button (access to the button confirmed), which erases the settings; reconfigure through the app.
