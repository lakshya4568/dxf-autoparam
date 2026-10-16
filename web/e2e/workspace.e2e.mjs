// End to end: the real Python engine serving the built app, driven in headless Chrome over the DevTools protocol (no test
// framework, no browser download: Node + the installed Chrome). It checks what a person relies on:
//   the sheet loads; a click on the canvas selects and inspects WITHOUT moving the camera; the wheel zooms about the cursor;
//   a layer can be hidden; a value is previewed and applied, then undone, and the camera never moves; the page's revision
//   follows the engine's.
//
//   bun run build && node e2e/workspace.e2e.mjs [--dxf FILE [--project FILE.autoparam.json]] [--out DIR] [--port 8799]
// By default it generates a two-cell box GAD with its known parametrization (e2e/make_fixture.py: no model call), so a unit is
// parametrized and a value can be previewed, applied and undone.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { requireFreePort } from "./harness.mjs";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const root = join(here, "../..");
const port = +(args.port || 8799);
const cdpPort = +(args["cdp-port"] || 9338);
const out = args.out || mkdtempSync(join(tmpdir(), "ws-e2e-"));
const chromePath = args.chrome || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const W = 1500, H = 950;
const base = `http://127.0.0.1:${port}`;
mkdirSync(out, { recursive: true });
let dxf = args.dxf ? resolve(args.dxf) : null;
let project = args.project ? resolve(args.project) : null;
if (!dxf) {
  const made = spawnSync("uv", ["run", "python", join(here, "make_fixture.py"), join(out, "fixture")], { cwd: root, encoding: "utf8" });
  if (made.status !== 0) throw new Error(`the e2e drawing could not be generated:\n${made.stderr.slice(-2000)}`);
  ({ dxf, project } = JSON.parse(made.stdout.trim().split("\n").pop()));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
}
const sameCam = (a, b) => a && b && Math.abs(a.cx - b.cx) < 1e-9 * Math.max(1, Math.abs(a.cx)) && Math.abs(a.cy - b.cy) < 1e-9 * Math.max(1, Math.abs(a.cy))
  && Math.abs(a.s - b.s) < 1e-12 * Math.max(1, a.s) && a.rot === b.rot;

await requireFreePort(base);
const server = spawn("uv", ["run", "dxf-autoparam", "serve", dxf, "--port", String(port), ...(project ? ["--project", project] : [])], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", (d) => (serverLog += d));
server.stderr.on("data", (d) => (serverLog += d));
const profile = mkdtempSync(join(tmpdir(), "ws-e2e-chrome-"));
let chrome = null, ws = null, id = 0;
const pending = new Map();
const send = (method, params = {}) => {
  const n = ++id;
  ws.send(JSON.stringify({ id: n, method, params }));
  return new Promise((res, rej) => pending.set(n, { res, rej }));
};
async function js(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
async function until(expr, ms = 20000) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const v = await js(expr).catch(() => null);
    if (v) return v;
    await sleep(100);
  }
  return null;
}
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(out, `${name}.png`), Buffer.from(r.data, "base64"));
}
const mouse = (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", buttons: type === "mouseReleased" ? 0 : 1, clickCount: 1, pointerType: "mouse", ...extra });
const cam = () => js("JSON.parse(JSON.stringify(window.__ws.state().cam))");

let code = 1;
try {
  // the engine
  let up = false;
  for (let k = 0; k < 300 && !up; k++) {
    try { up = (await fetch(`${base}/api/sheet`)).ok; } catch { await sleep(200); }
  }
  if (!up) throw new Error(`the server did not start:\n${serverLog.slice(-2000)}`);
  const html = await (await fetch(`${base}/`)).text();
  check("the server serves the built React app at /", html.includes("/app/assets/"), html.includes("/app/assets/") ? "" : "run `bun run build` first");

  // the browser
  chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${cdpPort}`, `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check",
    `--window-size=${W},${H}`, "about:blank"], { stdio: "ignore" });
  let targets;
  for (let k = 0; k < 100 && !targets; k++) {
    try { targets = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json(); } catch { await sleep(150); }
  }
  ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(m.error.message)) : p.res(m.result);
    }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__errors=[];addEventListener('error',e=>__errors.push(String(e.message)));addEventListener('unhandledrejection',e=>__errors.push(String(e.reason)));" });
  const t0 = Date.now();
  await send("Page.navigate", { url: `${base}/` });

  // 1 · the sheet loads and is fitted
  const n = await until("window.__ws && window.__ws.state().prims.length && window.__ws.state().fitted && window.__frame ? window.__ws.state().prims.length : 0", 60000);
  check("the sheet loads and draws", n > 0, `${n} primitives in ${Date.now() - t0} ms, frame ${await js("window.__frame && window.__frame.ms.toFixed(1)")} ms`);
  await sleep(300);
  await shot("01_sheet");

  // 2 · zoom into a view: the camera the person chose
  const gid = await js("(window.__ws.state().summary.groups.find(g => g.kind === 'view') || {}).id || null");
  if (gid) await js(`window.__ws.fitView(${JSON.stringify(gid)})`);
  await sleep(150);
  const chosen = await cam();

  // 3 · a click on the canvas selects and inspects, and does not move the camera
  const target = await js(`(() => {
    const s = window.__ws.state(); const c = s.cam; const rect = document.querySelector('[data-testid=canvas]').getBoundingClientRect();
    const scr = (x, y) => { const co = Math.cos(c.rot), si = Math.sin(c.rot), dx = x - c.cx, dy = y - c.cy; return [rect.left + s.W / 2 + c.s * (co * dx - si * dy), rect.top + s.H / 2 - c.s * (si * dx + co * dy)]; };
    for (const p of s.prims) {
      if (p.k !== 'p' || p.r !== 'structural' || !p.p || p.p.length < 4) continue;
      const [x, y] = scr((p.p[0] + p.p[2]) / 2, (p.p[1] + p.p[3]) / 2);
      if (x > rect.left + 20 && x < rect.right - 20 && y > rect.top + 20 && y < rect.bottom - 20) return { i: p.i, x, y };
    }
    return null;
  })()`);
  if (target) {
    await mouse("mouseMoved", target.x, target.y, { buttons: 0 });
    await mouse("mousePressed", target.x, target.y);
    await mouse("mouseReleased", target.x, target.y);
    const got = await until("window.__ws.state().entity ? { index: window.__ws.state().entity.index } : null", 10000);
    const rec = got ? got.index : null;
    const sel = await js("[...window.__ws.state().selection]");
    check("a click selects the entity under the cursor", sel.length === 1 && rec !== null, `clicked near entity ${target.i}, selected ${sel.join(",")}, inspected ${rec}`);
    check("a click does not move the camera", sameCam(chosen, await cam()));
    check("the inspector shows the entity record", await until("!!document.querySelector('[data-testid=inspector]')", 5000));
    await shot("02_selected");
  } else check("a click selects the entity under the cursor", false, "no structural line on screen to click");

  // 4 · wheel zoom about the cursor
  const before = await cam();
  const cx = 700, cy = 420;
  await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: cx, y: cy, deltaX: 0, deltaY: -240 });
  await sleep(120);
  const after = await cam();
  const anchored = await js(`(() => {
    const rect = document.querySelector('[data-testid=canvas]').getBoundingClientRect(); const s = window.__ws.state();
    const w = (c) => { const co = Math.cos(c.rot), si = Math.sin(c.rot), u = (${cx} - rect.left - s.W / 2) / c.s, v = -(${cy} - rect.top - s.H / 2) / c.s; return [c.cx + co * u + si * v, c.cy - si * u + co * v]; };
    const a = w(${JSON.stringify(before)}), b = w(s.cam); return Math.hypot(a[0] - b[0], a[1] - b[1]) * s.cam.s;
  })()`);
  check("the wheel zooms about the cursor", after.s > before.s * 1.1 && anchored < 1, `scale ×${(after.s / before.s).toFixed(2)}, point under cursor drifted ${anchored.toFixed(3)} px`);
  await js(`window.__ws.state().cam && (window.__ws.fitView(${JSON.stringify(gid)}))`);
  await sleep(100);

  // 5 · a layer can be hidden and shown again
  const layer = await js("(window.__ws.state().prims.find(p => p.r === 'structural') || {}).l");
  if (layer !== undefined) {
    await js(`window.__ws.toggleLayer(${JSON.stringify(layer)})`);
    await sleep(80);
    const hidden = await js(`window.__ws.state().hiddenLayers.has(${JSON.stringify(layer)})`);
    const drawnHidden = await js("window.__frame.drawn");
    await js(`window.__ws.toggleLayer(${JSON.stringify(layer)})`);
    await sleep(80);
    const drawnShown = await js("window.__frame.drawn");
    check("a layer hides and shows", hidden && drawnShown > drawnHidden, `layer ${layer}: ${drawnShown} drawn shown, ${drawnHidden} hidden`);
  }

  // 6 · preview, apply, undo: the camera never moves; the revision follows the engine
  const param = await js(`(async () => {
    const s = window.__ws.state().summary;
    for (const u of s.units.filter(u => u.parametrized)) {
      const info = await (await fetch('/api/sheet/unit?id=' + encodeURIComponent(u.id))).json();
      const p = (info.params || []).find(p => p.unit === 'mm' && p.value > 50 && p.kind !== 'level');
      if (p) return { key: p.key, value: p.value, unit: u.id };
    }
    return null;
  })()`);
  if (!param) {
    check("preview / apply / undo", false, "no parametrized unit with a length value on this drawing (open one that the engine parametrizes)");
  } else {
    await js(`window.__ws.fitView(${JSON.stringify(gid)})`);
    await sleep(100);
    const camBefore = await cam();
    const rev0 = await js("window.__ws.state().revision");
    const v1 = Math.round(param.value * 1.05);
    await js(`window.__ws.previewChange({ ${JSON.stringify(param.key)}: ${v1} })`);
    const prev = await js("(() => { const p = window.__ws.state().preview; return p && { ok: p.ok, n: p.ents.size, errors: p.errors }; })()");
    check("a preview regenerates without applying", prev && prev.n > 0 && (await js("window.__ws.state().revision")) === rev0, `${param.key} ${param.value} → ${v1}: ${prev?.n} entities, ok=${prev?.ok}${prev?.errors?.length ? ", " + prev.errors[0] : ""}`);
    check("a preview does not move the camera", sameCam(camBefore, await cam()));
    await shot("03_preview");
    if (prev?.ok) {
      const ok = await js(`window.__ws.applyChange({ ${JSON.stringify(param.key)}: ${v1} })`);
      const rev1 = await js("window.__ws.state().revision");
      const engineRev = (await (await fetch(`${base}/api/sheet`)).json()).revision;
      check("apply commits a new revision", ok && rev1 !== rev0, `revision ${rev0} → ${rev1}`);
      check("the page's revision is the engine's", rev1 === engineRev && (await until(`document.querySelector('[data-testid=revision]')?.textContent === 'rev ${engineRev}'`, 3000)), `page ${rev1}, engine ${engineRev}`);
      check("apply does not move the camera", sameCam(camBefore, await cam()));
      await shot("04_applied");
      await js("window.__ws.undo()");
      const rev2 = await js("window.__ws.state().revision");
      const valueBack = await js(`(async () => { const info = await (await fetch('/api/sheet/unit?id=${encodeURIComponent(param.unit)}')).json(); return (info.params.find(p => p.key === ${JSON.stringify(param.key)}) || {}).value; })()`);
      check("undo restores the value", Math.abs(valueBack - param.value) < 1e-6 && rev2 !== rev1, `${param.key} = ${valueBack}, revision ${rev2}`);
      check("undo does not move the camera", sameCam(camBefore, await cam()));
    }
  }

  // 7 · panels render with the engine's data
  for (const [tab, testid] of [["fidelity", "faithful"], ["layers", "layers-panel"], ["values", "values-panel"]]) {
    await js(`document.querySelector('[data-testid=tab-${tab}]').click()`);
    check(`the ${tab} panel renders`, await until(`!!document.querySelector('[data-testid=${testid}]')`, 8000));
  }
  await js("document.querySelector('[data-testid=agent-toggle]').click()");
  check("the agent dock opens", await until("!!document.querySelector('[data-testid=agent-panel]')", 8000));
  const sendDisabled = await js("document.querySelector('[data-testid=send]').disabled");
  const confirmShown = await js("!!document.querySelector('[data-testid=cost-confirm]')");
  check("the agent never starts without an instruction and a confirmation", sendDisabled && !confirmShown, `send disabled with no instruction: ${sendDisabled}, confirmation shown: ${confirmShown}`);
  await shot("05_panels");

  const errors = await js("window.__errors");
  check("no uncaught errors in the page", errors.length === 0, errors.slice(0, 3).join(" | "));
  code = results.every((r) => r.ok) ? 0 : 1;
} catch (e) {
  console.error(e);
  check("the e2e ran to the end", false, String(e).slice(0, 300));
} finally {
  writeFileSync(join(out, "e2e.json"), JSON.stringify({ dxf, project, results }, null, 1));
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} passed · screenshots and e2e.json in ${out}`);
  try { ws && ws.close(); } catch { /* the socket is already closed */ }
  if (chrome) chrome.kill("SIGTERM");
  server.kill("SIGTERM");
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
  process.exit(code);
}
