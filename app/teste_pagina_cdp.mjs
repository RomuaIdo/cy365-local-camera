// Drives static/index.html in headless Chrome through the DevTools protocol.
// Usage: node teste_pagina_cdp.mjs <page-url> <screenshot-dir>   (server must run with a fake camera)
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PAGE_URL = process.argv[2];
const SHOT_DIR = process.argv[3];
const CDP_PORT = 9341;
const profile = mkdtempSync(join(tmpdir(), "cy-qt-"));
const chrome = spawn("google-chrome-stable", ["--headless", "--no-sandbox", "--disable-gpu",
  `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, cond, extra = "") => {
  results.push([name, !!cond]);
  console.log(`[${cond ? "ok" : "FAILED"}] ${name} ${extra}`.trimEnd());
};

let target;
for (let i = 0; i < 60 && !target; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
    target = list.find((t) => t.type === "page");
  } catch (e) { /* browser still starting */ }
  if (!target) await sleep(200);
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
const exceptions = [];
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") {
    const d = msg.params.exceptionDetails;
    exceptions.push(d.exception?.description || d.text);
  }
});
const cdp = (method, params = {}) => new Promise((r) => {
  const id = ++seq;
  pending.set(id, r);
  ws.send(JSON.stringify({ id, method, params }));
});
const js = async (expr) => {
  const r = await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "JS error");
  return r.result.result.value;
};
const text = (id) => js(`document.getElementById('${id}').textContent`);
const hidden = (id) => js(`document.getElementById('${id}').hidden`);
const key = (k, ctrl = false) => js(`document.dispatchEvent(new KeyboardEvent('keydown', {key: ${JSON.stringify(k)}, ctrlKey: ${ctrl}})); 0`);
const click = (id) => js(`document.getElementById('${id}').click(); 0`);
const shot = async (name) => {
  const r = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(SHOT_DIR, name), Buffer.from(r.result.data, "base64"));
};
const viewport = (w, h) => cdp("Emulation.setDeviceMetricsOverride",
  { width: w, height: h, deviceScaleFactor: 1, mobile: false });

await cdp("Runtime.enable");
await cdp("Page.enable");
await viewport(1280, 800);
await cdp("Page.navigate", { url: PAGE_URL });
await sleep(1500);

// 1. Initial state: disconnected, connect dialog open, video screen active
check("disconnected: connect dialog visible", !(await hidden("modal-connect")));
check("disconnected: pill says Disconnected", (await text("conn-pill")).includes("Disconnected"));
check("disconnected: video screen is the active one", !(await hidden("screen-video")));

// 2. Keyboard: Ctrl+1..5 switch screens
await key("2", true); await sleep(100);
check("Ctrl+2 shows Controls", !(await hidden("screen-controls")) && (await hidden("screen-video")));
await key("3", true); await sleep(100);
check("Ctrl+3 shows Information", !(await hidden("screen-info")));
await key("4", true); await sleep(100);
check("Ctrl+4 shows Network", !(await hidden("screen-network")));
await key("5", true); await sleep(100);
check("Ctrl+5 shows About", !(await hidden("screen-about")));
await key("1", true); await sleep(100);
check("Ctrl+1 back to Video", !(await hidden("screen-video")));

// 3. Validation error shows in the dialog
await click("btn-connect"); await sleep(200);
check("empty password: error in dialog", (await text("connect-error")).includes("Password required"));

// 4. Connect: password is cleared right after sending
await js(`document.getElementById('input-password').value = 'example-pwd'; 0`);
await click("btn-connect");
await sleep(2000);
check("connect: pill says Connected", (await text("conn-pill")).includes("Connected"));
check("connect: dialog closed", await hidden("modal-connect"));
check("connect: password field cleared", (await js(`document.getElementById('input-password').value`)) === "");
check("connect: status bar shows camera", (await text("status-camera")).includes("connected"));

// 5. Video: pause/resume button and Space key
check("video: starts paused (server default)", (await text("video-badge")).includes("Paused"));
await click("btn-pause-video"); await sleep(600);
check("video: badge Live after start", (await text("video-badge")).includes("Live"));
check("video: button now offers pause", (await text("btn-pause-video")).includes("Pause"));
check("video: paused message hidden while live", await hidden("video-paused"));
await click("btn-pause-video"); await sleep(600);
check("pause: button now offers resume", (await text("btn-pause-video")).includes("Resume"));
check("pause: paused message visible", !(await hidden("video-paused")));
await js(`document.dispatchEvent(new KeyboardEvent('keydown', {key: ' '})); 0`); await sleep(600);
check("Space: starts video", (await text("btn-pause-video")).includes("Pause"));
await js(`document.dispatchEvent(new KeyboardEvent('keydown', {key: ' '})); 0`); await sleep(600);
check("Space: pauses video again", (await text("btn-pause-video")).includes("Resume"));

// 6. Audio switch starts the server stream and points the player at /audio.wav
await js(`(() => { const s = document.getElementById('switch-audio'); s.checked = true; s.dispatchEvent(new Event('change')); return 0; })()`);
await sleep(800);
check("audio on: status bar says on", (await text("status-audio")).includes("Audio on"));
check("audio on: player plays a MediaStream fed by Web Audio",
  (await js(`document.getElementById('audio-player').srcObject !== null`)) === true);
await js(`(() => { const s = document.getElementById('switch-audio'); s.checked = false; s.dispatchEvent(new Event('change')); return 0; })()`);
await sleep(800);
check("audio off: player stream released", (await js(`document.getElementById('audio-player').srcObject === null`)) === true);

// 7. Volume slider updates the label
await js(`(() => { const r = document.getElementById('slider-volume'); r.value = 40; r.dispatchEvent(new Event('input')); return 0; })()`);
check("volume slider: label shows 40%", (await text("volume-value")) === "40%");

// 8. Controls: switches show the value read back from the camera
await key("2", true); await sleep(300);
await js(`(() => { const s = document.getElementById('switch-indicator'); s.checked = false; s.dispatchEvent(new Event('change')); return 0; })()`);
await sleep(1500);
check("indicator off: reads back Off", (await text("indicator-state")) === "Off");
await js(`(() => { const s = document.getElementById('switch-indicator'); s.checked = true; s.dispatchEvent(new Event('change')); return 0; })()`);
await sleep(1500);
check("indicator on: reads back On", (await text("indicator-state")) === "On");
await js(`(() => { const s = document.getElementById('select-ir'); s.value = '2'; s.dispatchEvent(new Event('change')); return 0; })()`);
await sleep(1000);
check("infrared: combo shows mode read back (2)", (await js(`document.getElementById('select-ir').value`)) === "2");
await shot("controls_1280x800.png");

// 9. Information: loads on open, shows camera data
await key("3", true); await sleep(1200);
check("info: battery 100%", (await text("info-battery")) === "100%");
check("info: firmware shown", (await text("info-firmware")) === "CYCAM_T99_v32_0226");
check("info: charging shown", (await text("info-charging")).includes("Yes"));
check("info: status bar battery", (await text("status-battery")).includes("100%"));
await shot("info_1280x800.png");

// 10. Network: read only, SSID and mode
await key("4", true); await sleep(1000);
check("network: SSID from camera", (await text("net-ssid")) === "fake-network");
check("network: mode 1 is Station", (await text("net-mode")).includes("Station"));
check("network: no write controls on screen",
  (await js(`document.querySelectorAll('#screen-network input, #screen-network select').length`)) === 0);
await shot("network_1280x800.png");

// 11. Errors: menu actions and status bar
await key("1", true); await sleep(300);
await js(`document.querySelector('[data-menu=camera]').click(); 0`); await sleep(200);
check("Camera menu opens", await js(`document.getElementById('menu-camera').classList.contains('open')`));
await js(`document.querySelector('[data-action=disconnect]').click(); 0`); await sleep(1500);
check("disconnect: pill says Disconnected", (await text("conn-pill")).includes("Disconnected"));
check("disconnect: dialog reopens", !(await hidden("modal-connect")));
check("disconnect: status bar message", (await text("status-message")).includes("disconnected"));
await js(`document.querySelector('[data-menu=camera]').click(); 0`); await sleep(100);
await js(`document.querySelector('[data-menu=camera]').click(); 0`);

// 12. Theme from Exibir menu (in memory only)
await js(`document.querySelector('[data-menu=view]').click(); 0`);
await js(`document.querySelector('[data-action=theme-light]').click(); 0`); await sleep(200);
check("theme: light applied", (await js(`document.documentElement.getAttribute('data-theme')`)) === "light");
await js(`document.querySelector('[data-action=theme-dark]').click(); 0`); await sleep(200);
check("theme: dark applied", (await js(`document.documentElement.getAttribute('data-theme')`)) === "dark");

// 13. Layout at 960x600 (minimum window): sidebar becomes icon-only
await viewport(960, 600); await sleep(400);
await key("1", true); await sleep(300);
const sidebarAt960 = await js(`document.querySelector('.sidebar').getBoundingClientRect().width`);
check("960px: full sidebar (200px); collapse applies below 960", sidebarAt960 === 200, `width=${sidebarAt960}`);
await shot("video_960x600.png");
await viewport(959, 600); await sleep(400);
const sidebarAt959 = await js(`document.querySelector('.sidebar').getBoundingClientRect().width`);
check("959px: icon-only sidebar (56px)", sidebarAt959 === 56, `width=${sidebarAt959}`);
await viewport(1280, 800); await sleep(400);
await key("1", true); await sleep(300);
const sidebarWide = await js(`document.querySelector('.sidebar').getBoundingClientRect().width`);
check("1280px: sidebar 200px", sidebarWide === 200, `width=${sidebarWide}`);
await shot("video_1280x800.png");

// 14. Storage and JavaScript errors
const storage = await js(`localStorage.length + sessionStorage.length + (document.cookie ? 1 : 0)`);
check("no localStorage, sessionStorage or cookies", storage === 0, `count=${storage}`);
check("no JavaScript exceptions", exceptions.length === 0, exceptions.join(" | "));

ws.close();
chrome.kill();
const failed = results.filter(([, ok]) => !ok).length;
console.log(`\nRESULT: ${results.length - failed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
