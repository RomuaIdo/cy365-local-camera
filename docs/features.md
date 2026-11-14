# Camera Resources and Command Mapping

Consolidated mapping of the hardware and software resources of the CY365 / SHIX camera ecosystem. The mapping was derived from decompilation of `jadx_src/sources/com/shix/shixipc/utils/CommonUtil.java` and checked against the decrypted packets of a local capture.

## Resource Overview

| Resource | Command(s) | Main fields | Read / Write | Proven in capture? | Hardware required | Priority for new app |
|:---|:---|:---|:---:|:---:|:---:|:---:|
| **Authentication / Login** | `check_user` (100) | `user, pwd, devmac` | Read (validation) | **Yes** (packet #387, response #452) | No | **1 (Essential)** |
| **Video streaming** | `stream` (111) | `video: 1/0, camsmode: 0, user, pwd` | Write / Stream | **Yes** (packets #518, #3670; responses #526, #3712) | CMOS sensor | **1 (Essential)** |
| **Live audio streaming** | `stream` (111) | `audio: 1/0, user, pwd` | Write / Stream | **Yes** (packets #1784, #2806; responses #1831, #2837) | Internal microphone | **1 (Essential)** |
| **Wi-Fi network query** | `get_wifi` (112) | `user, pwd` | Read | No | Wi-Fi module | **1 (Essential)** |
| **Network scan** | `scan_wifi` (113) | `user, pwd` | Read | No | Wi-Fi module | **1 (Essential)** |
| **Wi-Fi configuration** | `set_wifi` (114) | `wifissid, wifipwd, encwifissid, encwifipwd, encryption, user, pwd` | Write | No (direct LAN in capture) | Wi-Fi module | **1 (Essential)** |
| **Clock synchronization** | `set_datetime` (126) | `time, timeZone, ntpSwitch, dstSwitch, ntpServer, user, pwd` | Write | **Yes** (response to cmd 126 in packet #458) | Internal RTC | **1 (Essential)** |
| **General status / telemetry** | `get_parms` (101) | `user, pwd` (returns: `power, charging, sysver, sensor, icut, lamp, bright, contrast, rate_bit`) | Read | **Yes** (packet #535) | Battery / ADC | **2 (Important)** |
| **White light control** | `get_whiteLight` (305), `set_whiteLight` (304) | `status` (0: off, 1: on, 2: auto), `user, pwd` | Read / Write | **Yes** (response 305 in packet #561) | White LEDs | **2 (Important)** |
| **Two-way talk (intercom)** | `talk_send` / `start_talk` (300 / 129), `end_talk` (130) | `user, pwd` (audio sent via channel 3 in G.711A) | Write / Stream | No | Speaker | **2 (Important)** |
| **Audio volume control** | `get_vol` (134), `set_vol` (135) | `vol` (0-100), `user, pwd` | Read / Write | No | Audio amplifier | **2 (Important)** |
| **PIR / presence alarm** | `get_alarm` (107), `set_alarm` (108) | `pirenable, pirsensitive, pirvideo, pirvideotime, pirDelayTime, pirPush, user, pwd` | Read / Write | [HYPOTHESIS] Partial (Resp 126) | PIR sensor | **2 (Important)** |
| **SD capacity / formatting** | `get_sd` (110), `set_sd` (110) | `coverage: 0/1, format: 0/1, user, pwd` | Read / Write | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **Local recording schedule** | `get_record_param` (199), `set_record_param` (122) | `recordcov, start_time, end_time, record_time, bitStream, recordAudio, timerecord` | Read / Write | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **Recording calendar** | `get_record_day` (205) | `year, month, user, pwd` | Read | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **Recorded file list** | `get_record_list` (206) | `year, month, day, hour, user, pwd` | Read | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **SD playback / replay** | `play_record_file` (207) | `filename, offset, user, pwd` | Write / Stream | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **SD file deletion** | `del_record_file` (207 / 119) | `filename, user, pwd` | Write | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **Reboot / factory reset** | `dev_control` (102) | `param: 0/1, value: 1, user, pwd` | Write | No | MCU / SoC | **2 (Important)** |
| **Image settings (color / mirror-flip)** | `dev_control` (102) | `param: 2 (rotmir), 3 (bright), 4 (contrast)` | Write | No | CMOS sensor | **2 (Important)** |
| **Pan/tilt movement (PTZ)** | `ptz_control` (128) | `parms: 0/1, value: 0..7/reset, user, pwd` | Write | No | Pan/tilt motors | **2 (if hardware is present)** |
| **User management** | `get_user` (103), `add_user` (104), `edit_user` (106), `del_user` (105) | `user, pwd, newUser, newPwd, jurisdiction` | Read / Write | No | No | **2 (Important)** |
| **Raw file download** | `start_videofiles` (117), `stop_videofiles` (120), `get_videofiles` (116) | `filename, user, pwd` | Read / Write | No | MicroSD slot | **3 (not applicable: no SD slot)** |
| **Local firmware update** | `upload_file_request` (201), `upload_file` (202) | `filename, filesize, offset, user, pwd` | Write | No | SPI flash | **2 (Important)** |
| **Push notifications (CY Cloud)** | `set_cypush` (1) | `pushIp, pushPort, pushInterval, cyAdmin, cyPwd, isPushPic, isPushVideo, cyToken` | Write | **Yes** (packet #455, response #468) | WAN connection | **3 (Discard / Ads)** |
| **Cloud service (support)** | `get_cloudsupport` (9000) | `user, pwd` | Read | **Yes** (packet #522, response #609) | WAN connection | **3 (Discard / Ads)** |
| **Cloud subscription** | `get_cloudinfo` (9002), `set_cloudinfo` (9001), `del_cloudinfo` (9003) | `creatTime, days, buyType, user, pwd` | Read / Write | **Yes** (response 9002 in packet #662) | WAN connection | **3 (Discard / Ads)** |
| **Remote OTA update** | `check_ota` | `user, pwd, sysver` | Read | No | WAN connection | **3 (Discard / Cloud)** |
| **3D printer (bed / nozzle)** | `set_bedtemp` (300/301), `get_temp` (302) | `temp, user, pwd` | Read / Write | No | 3D printer (serial) | **3 (hardware-specific)** |
| **3D printer (motors / fan)** | `set_startmotors` (306), `set_startfan` (308) | `user, pwd` | Write | No | 3D printer (serial) | **3 (hardware-specific)** |
| **3D printer (job / G-code)** | `pr_connect` (310), `pr_start` (313), `pr_pause` (314), `down_file` (507) | `user, pwd` | Write / Stream | No | 3D printer (serial) | **3 (hardware-specific)** |

---

## Implementation Notes for the New Application

1. **Command protocol**: All commands use channel 0 (`0xD0 | 00 | seq`), preceded by the header `06 0a a0 80` and a little-endian 32-bit length.
2. **Development priorities**:
   - Only the resources marked **Priority 1** are needed to obtain video, audio and a working Wi-Fi connection on any local or remote network.
   - **Priority 2** resources add value for cameras with a battery, an SD card and night-vision sensors.
   - **Priority 3** resources (the manufacturer's cloud, proprietary centralized push and 3D printer) should be omitted from an independent client to keep the application clean, free of telemetry and focused on local privacy.
