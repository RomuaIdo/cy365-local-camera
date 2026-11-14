// Live-audio test in headless Chrome: delay table, error and reconnect, volume and mute.
// Usage: node teste_audio_delay_cdp.mjs <base-url> <password> [seconds]
// The server must run with --audio-feed (real time) or --audio-burst (bursts) from teste_servidor_falso.py.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [BASE, PASSWORD, SECONDS = "10"] = process.argv.slice(2);
const DURATION_S = Number(SECONDS);
const PORT = 9352;
const profile = mkdtempSync(join(tmpdir(), "cy-audio-"));
const chrome = spawn("google-chrome-stable", ["--headless", "--no-sandbox", "--disable-gpu",
  "--autoplay-policy=no-user-gesture-required", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore", detached: true });
const stopChrome = () => { try { process.kill(-chrome.pid); } catch (e) { /* already gone */ } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, cond, extra = "") => {
  results.push([name, !!cond]);
  console.log(`[${cond ? "ok" : "FAILED"}] ${name} ${extra}`.trimEnd());
};

const conn = await fetch(`${BASE}/api/conectar`, { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pwd: PASSWORD }) });
if (conn.status !== 200) { console.log("connect failed", conn.status); stopChrome(); process.exit(1); }

let target;
for (let i = 0; i < 60 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); }
  catch (e) { /* browser starting */ }
  if (!target) await sleep(200);
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
let failAudio = false;  // when true, /audio.wav requests are failed by the interception
ws.addEventListener("message", async (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
  if (msg.method === "Fetch.requestPaused") {
    const { requestId } = msg.params;
    const method = failAudio ? "Fetch.failRequest" : "Fetch.continueRequest";
    cdp(method, failAudio ? { requestId, errorReason: "Failed" } : { requestId });
  }
});
const cdp = (method, params = {}) => new Promise((r) => { const id = ++seq; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
// userGesture lets audio.play() and clicks behave as a real user would
const js = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true,
  returnByValue: true, userGesture: true })).result.result.value;
const playerState = () => js(`(() => {
  const a = document.getElementById('audio-player');
  return { ahead: Number(a.dataset.aheadMs || -1), underruns: Number(a.dataset.underruns || 0), paused: a.paused, muted: a.muted, volume: a.volume,
           error: a.error ? a.error.code : null, hasStream: !!a.srcObject,
           status: document.getElementById('status-message').textContent,
           reconnect: !document.getElementById('btn-reconnect-audio').hidden };
})()`);

await cdp("Runtime.enable");
await cdp("Fetch.enable", { patterns: [{ urlPattern: "*audio.wav*" }] });
await cdp("Page.navigate", { url: `${BASE}/` });
await sleep(1500);

// 1. error path: the first /audio.wav request fails -> message and reconnect button
failAudio = true;
await js(`document.getElementById('switch-audio').click(); 0`);
await sleep(1500);
let st = await playerState();
check("error: status bar says the audio was interrupted", st.status.includes("Audio interrupted"), st.status);
check("error: reconnect button offered", st.reconnect === true);

// 2. reconnect: requests succeed again -> audio runs
failAudio = false;
await js(`document.getElementById('btn-reconnect-audio').click(); 0`);
await sleep(1500);
st = await playerState();
check("reconnect: stream running (ahead > 0)", st.ahead > 0, `ahead=${st.ahead}ms`);
check("reconnect: no error shown, button hidden", !st.reconnect && st.error === null);

// 3. delay table: ahead of the playhead (buffered in the page) over the run
const rows = [];
const t0 = Date.now();
while ((Date.now() - t0) / 1000 < DURATION_S) {
  await sleep(500);
  const s = await playerState();
  const elapsed = (Date.now() - t0) / 1000;
  rows.push({ elapsed, ahead: s.ahead, paused: s.paused, error: s.error });
  console.log(`t=${elapsed.toFixed(1)}s ahead_ms=${s.ahead} paused=${s.paused} error=${s.error}`);
}
const at = (sec) => rows.reduce((best, r) => (Math.abs(r.elapsed - sec) < Math.abs(best.elapsed - sec) ? r : best));
for (const sec of [2, 5, DURATION_S]) {
  const r = at(sec);
  console.log(`TABLE at ${sec}s: ahead_ms=${r.ahead} paused=${r.paused} error=${r.error}`);
}
const maxAhead = Math.max(...rows.map((r) => r.ahead));
check("delay: ahead stays below 1000 ms", maxAhead < 1000, `max=${maxAhead}ms`);
check("delay: ahead does not grow (last <= first + 200 ms)", rows.at(-1).ahead <= rows[0].ahead + 200,
  `first=${rows[0].ahead} last=${rows.at(-1).ahead}`);
const underrunsEnd = (await playerState()).underruns;
console.log(`underruns (gaps restarted with a lead): ${underrunsEnd}`);
check("playback: not paused, no error", rows.every((r) => !r.paused && r.error === null));

// 4. volume and mute act on the <audio> element itself
await js(`(() => { const r = document.getElementById('slider-volume'); r.value = 30; r.dispatchEvent(new Event('input')); return 0; })()`);
st = await playerState();
check("volume: slider 30% sets audio.volume 0.3", Math.abs(st.volume - 0.3) < 1e-6, `volume=${st.volume}`);
await js(`document.getElementById('btn-mute-audio').click(); 0`);
st = await playerState();
check("mute: audio.muted true", st.muted === true);
check("mute: volume kept while muted", Math.abs(st.volume - 0.3) < 1e-6, `volume=${st.volume}`);
await js(`document.getElementById('btn-mute-audio').click(); 0`);
st = await playerState();
check("unmute: audio.muted false", st.muted === false);

// 5. switching audio off stops playback and releases the stream
await js(`document.getElementById('switch-audio').click(); 0`);
await sleep(800);
st = await playerState();
check("off: player paused and stream released", st.paused === true && st.hasStream === false);

ws.close();
stopChrome();
const failed = results.filter(([, ok]) => !ok).length;
console.log(`\nRESULT: ${results.length - failed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
