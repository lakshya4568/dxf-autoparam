// Drive the sheet workspace in a headless Chrome over the DevTools protocol: wait for the sheet, run page actions,
// take screenshots, and measure frame times (render, zoom, pan, hit test). No test framework, no download: Chrome + Node.
//
//   node tools/bench_ui.mjs --url http://127.0.0.1:8797/ --out /tmp/ws --steps steps.json
//   steps: [{"js": "openView('V04', true)", "wait": 800, "shot": "view"}, {"bench": true}]
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const url = args.url || "http://127.0.0.1:8797/";
const out = args.out || "/tmp/ws-shots";
const steps = args.steps ? JSON.parse(readFileSync(args.steps, "utf8")) : [{ shot: "sheet" }, { bench: true }];
const W = +(args.width || 1680), H = +(args.height || 1000);
const chromePath = args.chrome || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = +(args.port || 9337);
mkdirSync(out, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), "ws-chrome-"));
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run",
  "--no-default-browser-check", `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pending = new Map();
function send(method, params = {}) { const n = ++id; ws.send(JSON.stringify({ id: n, method, params })); return new Promise((res, rej) => pending.set(n, { res, rej })); }
async function evaluate(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png" });
  const p = join(out, `${name}.png`); writeFileSync(p, Buffer.from(r.data, "base64")); return p;
}
const report = { url, viewport: [W, H], steps: [] };
try {
  let targets;
  for (let k = 0; k < 50; k++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; } catch { await sleep(200); } }
  const page = targets.find((t) => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } });
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  const t0 = Date.now();
  await send("Page.navigate", { url });
  let prims = 0;
  for (let k = 0; k < 600; k++) { prims = await evaluate("window.__ws ? window.__ws.prims : 0").catch(() => 0); if (prims > 0) break; await sleep(100); }
  report.load_ms = Date.now() - t0; report.prims = prims;
  await sleep(300);
  for (const st of steps) {
    const row = { ...st };
    if (st.js) row.result = await evaluate(st.js);
    if (st.wait) await sleep(st.wait);
    if (st.bench) {
      row.bench = await evaluate(`(async () => {
        const w = window.__ws; const fr = []; const s0 = w.cam.s;
        w.fit(w.sheet()); for (let k = 0; k < 10; k++) fr.push(w.render());
        const full = fr.slice(); fr.length = 0;
        for (let k = 0; k < 20; k++) { w.cam.s *= 1.12; fr.push(w.render()); }
        const zoom = fr.slice(); fr.length = 0;
        for (let k = 0; k < 20; k++) { w.cam.x += 40 / w.cam.s; fr.push(w.render()); }
        const pan = fr.slice();
        const cv = document.querySelector("#cv"); const r = cv.getBoundingClientRect(); const ht = [];
        for (let k = 0; k < 200; k++) { const t = performance.now(); w.pick(Math.random() * r.width, Math.random() * r.height); ht.push(performance.now() - t); }
        const t = performance.now(); w.boxSelect([w.cam.x - 1e9, w.cam.y - 1e9], [w.cam.x + 1e9, w.cam.y + 1e9], true); const box = performance.now() - t;
        const st = (a) => { a = a.slice().sort((x, y) => x - y); return { median: +a[a.length >> 1].toFixed(2), p95: +a[Math.floor(a.length * 0.95)].toFixed(2), max: +a[a.length - 1].toFixed(2) }; };
        w.cam.s = s0; w.draw();
        return { full_sheet_render: st(full), zoom_render: st(zoom), pan_render: st(pan), hit_test: st(ht), crossing_all_ms: +box.toFixed(1) };
      })()`);
    }
    if (st.shot) row.file = await shot(st.shot);
    report.steps.push(row);
  }
  report.console_errors = await evaluate("window.__errors || []").catch(() => []);
} finally {
  writeFileSync(join(out, "report.json"), JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
  try { ws && ws.close(); } catch {}
  chrome.kill("SIGTERM"); await sleep(300); try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
