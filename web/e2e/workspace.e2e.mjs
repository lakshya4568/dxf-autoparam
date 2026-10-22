// End to end: the real Python engine serving the built app, driven in headless Chrome over the DevTools protocol (no test
// framework, no browser download: Node + the installed Chrome). It checks what a person relies on:
//   the sheet loads; a click on the canvas selects and inspects WITHOUT moving the camera; the wheel zooms about the cursor;
//   a layer can be hidden; a value is previewed and applied, then undone, and the camera never moves; the page's revision
//   follows the engine's.
//
//   bun run build && node e2e/workspace.e2e.mjs [--dxf FILE [--project FILE.autoparam.json]] [--out DIR] [--port 8799] [--pinned 1]
// By default it generates a two-cell box GAD with its known parametrization (e2e/make_fixture.py: no model call), so a unit is
// parametrized and a value can be previewed, applied and undone.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { requireFreePort } from "./harness.mjs";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const root = join(here, "../..");
const port = +(args.port || 8799);
const cdpPort = +(args["cdp-port"] || 9338);
// absolute: the screenshots are written from here (web/) and the server's --state-dir is read from the repo root — a relative path meant two places
const out = resolve(args.out || mkdtempSync(join(tmpdir(), "ws-e2e-")));
const chromePath = args.chrome || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const W = 1500, H = 950;
const base = `http://127.0.0.1:${port}`;
mkdirSync(out, { recursive: true });
let dxf = args.dxf ? resolve(args.dxf) : null;
let project = args.project ? resolve(args.project) : null;
if (!dxf) {
  const made = spawnSync("uv", ["run", "python", join(here, "make_fixture.py"), join(out, "fixture"), ...(args.pinned ? ["pinned"] : [])], { cwd: root, encoding: "utf8" });
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
// --state-dir: a test server keeps its work in the test's own folder, never in the person's (where the work on a real drawing is kept)
const stateDir = join(out, "state");
const server = spawn("uv", ["run", "dxf-autoparam", "serve", dxf, "--port", String(port), "--state-dir", stateDir, ...(project ? ["--project", project] : [])], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
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

  // 1b · each view in its own tab: only its entities, the camera on it, the cursor said in its own frame (mm from its origin, RL where it states a
  // level); "Sheet" brings the whole sheet back. The sheet itself is not changed by looking at it this way.
  {
    const views = await js("window.__ws.state().summary.groups.filter(g => g.kind === 'view').map(g => g.id)");
    check("a tab per view beside the whole sheet", await until(`document.querySelectorAll('[data-testid^=view-tab-]').length === ${views.length + 1}`, 5000), views.join(", "));
    const drawnSheet = await js("window.__frame && window.__frame.drawn");
    const v = views[0];
    await js(`document.querySelector('[data-testid=view-tab-${v}]').click()`);
    const onlyIt = await until(`window.__ws.state().viewTab === ${JSON.stringify(v)} && window.__frame && window.__frame.drawn < ${drawnSheet}`, 5000);
    const own = await js(`window.__ws.state().prims.filter(p => p.v === ${JSON.stringify(v)}).length`);
    check("a view's tab draws only that view", onlyIt, `${drawnSheet} primitives on the sheet, ${await js("window.__frame.drawn")} in ${v} (it has ${own})`);
    const rect = await js("(() => { const r = document.querySelector('[data-testid=canvas]').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()");
    await mouse("mouseMoved", rect[0], rect[1], { buttons: 0 });
    const said = await until("/mm/.test(document.querySelector('[data-testid=cursor-readout]')?.textContent || '')", 3000);
    check("the cursor is said in the view's own frame (mm from its origin)", said, await js("document.querySelector('[data-testid=cursor-readout]')?.textContent"));
    const frame = await js(`(window.__ws.state().summary.groups.find(g => g.id === ${JSON.stringify(v)}) || {}).local || null`);
    const back = frame && await js(`(() => { const f = ${JSON.stringify(frame)}; const x = f.origin[0] + 1234.5 / f.mm_per_unit, y = f.origin[1] - 77 / f.mm_per_unit;
      const lx = (x - f.origin[0]) * f.mm_per_unit, ly = (y - f.origin[1]) * f.mm_per_unit; return [lx, ly]; })()`);
    check("the view's frame maps a point to the sheet and back", !!back && Math.abs(back[0] - 1234.5) < 1e-6 && Math.abs(back[1] + 77) < 1e-6, JSON.stringify(frame));
    await shot("01b_view_tab");
    await js("document.querySelector('[data-testid=view-tab-sheet]').click()");
    check("Sheet brings the whole sheet back", await until(`window.__ws.state().viewTab === null && window.__frame.drawn >= ${drawnSheet}`, 5000));
  }

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
      if (p) return { key: p.key, name: p.name, value: p.value, unit: u.id };
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

  // 6b · the person's own path: the Values tab, a click on a value opens its editor, typing previews it. (Once a click on a value did nothing and said
  // nothing: the engine sent {} where the page iterated a list, and the rejection was swallowed. Every other check here went through window.__ws.)
  if (param) {
    const rev = await js("window.__ws.state().revision");
    await js("document.querySelector('[data-testid=tab-values]').click()");
    await js(`window.__ws.openUnit(${JSON.stringify(param.unit)})`);
    // a value shared across views is listed once, under "Shared across views"; one that only this unit has is under its named values
    const row = `[data-testid="param-${param.name}"], [data-testid="shared-${param.name}"]`;
    check("the Values panel lists the unit's values", await until(`!!document.querySelector(${JSON.stringify(row)})`, 8000), `${param.unit}.${param.name}`);
    // the unit's parts as a tree: a click selects the part's own geometry on the drawing, and the camera stays where it is
    const partsShown = await until("!!document.querySelector('[data-testid=parts-group]')", 8000);
    let partPicked = false;
    if (partsShown) {
      await js("document.querySelector('[data-testid=parts-group]').open = true");
      const cam0 = await js("JSON.stringify(window.__ws.state().cam)");
      const part = await js("[...document.querySelectorAll('[data-testid=parts-group] button[data-testid^=part-]')].find((b) => !b.disabled)?.dataset.testid");
      if (part) {
        await js(`document.querySelector('[data-testid=${JSON.stringify(part)}]').click()`);
        partPicked = (await until("window.__ws.state().selection.size > 0", 3000)) && (await js("JSON.stringify(window.__ws.state().cam)")) === cam0;
        await js("window.__ws.select(null)");
      }
    }
    check("the parts list shows the unit's parts; a click selects a part's own geometry and the camera stays", partsShown && partPicked);
    check("and says how many of the unit's dimensions a named value drives", await until("/Dimensions: \\d+ of \\d+ change with a named value/.test(document.querySelector('[data-testid=dimension-drive]')?.textContent || '')", 20000), await js("document.querySelector('[data-testid=dimension-drive]')?.textContent"));
    await js(`document.querySelector(${JSON.stringify(row)}).click()`);
    check("a click on a value opens its editor", await until("!!document.querySelector('[data-testid=param-editor]')", 60000), param.key);
    check("a click on a value says what it moves", await until("!!window.__ws.state().highlight", 5000));
    // the editor is a spinner: no Apply, no slider; a step changes the drawing at once, and the original of what changed is shown dashed under it
    check("the editor has a spinner and no Apply, Reset or slider", await js("!!document.querySelector('[data-testid=param-inc]') && !!document.querySelector('[data-testid=param-dec]') && !document.querySelector('[data-testid=apply]') && !document.querySelector('[data-testid=param-reset]') && !document.querySelector('[data-testid=param-editor] [data-testid=show-original]') && !document.querySelector('[data-testid=param-editor] input[type=range]')"));
    const val = () => js(`window.__ws.state().summary.values[${JSON.stringify(param.key)}]`);
    const sig = () => js("JSON.stringify(window.__ws.state().prims.map((p) => [p.i, p.p, p.at]).sort((a, b) => a[0] - b[0] || String(a[1]).localeCompare(String(b[1]))))");
    const v0 = await val();
    let sig0 = await sig();
    // which side stays when it changes: the editor says who decided and on what evidence; a person's choice replaces the engine's default (at the drawn value it moves nothing yet)
    check("the editor says which side of the value stays when it changes, and who decided", await until("!!document.querySelector('[data-testid=growth-line]') && /engine|your choice|set-out/.test(document.querySelector('[data-testid=growth-by]')?.textContent || '')", 30000), await js("document.querySelector('[data-testid=growth-by]')?.textContent"));
    const firstPressed = () => js("[...document.querySelector('[data-testid=growth-line]').querySelectorAll('button')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.testid).join()");
    const atDrawn = await js(`(async () => { const i = await (await fetch('/api/sheet/unit?id=' + encodeURIComponent(${JSON.stringify(param.unit)}))).json(); const q = (i.params || []).find((x) => x.key === ${JSON.stringify(param.key)}); return !!q && Math.abs(q.value - q.drawn) < 1e-9; })()`);
    const sideBefore = await firstPressed();
    const other = ["growth-start", "growth-end"].find((t) => t !== sideBefore);
    if (await js("!!document.querySelector('[data-testid=growth-undecided]')")) {
      // no side can stay for this value (the engine says why): choosing one is refused with the reason; settling it is step 6d
      check("an undecided value says so, and offers the ways to settle it instead of a side that cannot stay", await js("!!document.querySelector('[data-testid=settle-ways]')"));
    } else {
      await js(`document.querySelector('[data-testid=growth-line] [data-testid=${other}]').click()`);
      check(`choosing a side makes it the person's own plan${atDrawn ? ", and the drawing does not change" : " (the value is stepped already: the drawing follows the side)"}`,
        await until("/your choice/.test(document.querySelector('[data-testid=growth-by]')?.textContent || '')", 60000) && (await firstPressed()) === other && (!atDrawn || (await sig()) === sig0), `${sideBefore || "none"} → ${other}`);
    }
    sig0 = await sig(); // the stepping below begins from here
    await shot("04a_growth_choice");
    const revStep = await js("window.__ws.state().revision"); // the choice above is a revision of its own: the step is the next one
    await js("document.querySelector('[data-testid=param-inc]').click()");
    check("one step up changes the value and the geometry, with nothing applied by hand", await until(`window.__ws.state().revision > ${revStep} && window.__ws.state().summary.values[${JSON.stringify(param.key)}] > ${v0}`, 60000) && (await val()) > v0 && (await sig()) !== sig0, `${param.key}: ${v0} → ${await val()}`);
    check("the original of what a step changed is shown dashed, under the drawing as it is now", await until("window.__ws.state().overlays.original === true && (window.__ws.state().original?.prims.length ?? 0) > 0", 20000));
    const reads = () => js("performance.getEntriesByType('resource').filter((e) => e.name.includes('/api/sheet/original')).length");
    const readsAfterFirst = await reads();
    const step1 = (await val()) - v0;
    await js("document.querySelector('[data-testid=param-inc]').click()");
    await js("document.querySelector('[data-testid=param-inc]').click()");
    check("three steps up in a row add three equal steps", await until(`Math.abs(window.__ws.state().summary.values[${JSON.stringify(param.key)}] - ${v0 + 3 * step1}) < 1e-6`, 60000) && !(await js("!!document.querySelector('[data-testid=param-error]')")), `${v0} + 3 × ${step1}`);
    check("the steps of one value read the original no more than once (an entity's original never changes)", (await reads()) <= readsAfterFirst + 1, `${readsAfterFirst} → ${await reads()}`);
    const v3 = await val();
    await shot("04b_value_editor");
    await sleep(150);
    await shot("04c_original_dashed");
    await js("document.querySelector('[data-testid=show-original]').click()");
    check("the Original switch in the top bar hides it", await until("window.__ws.state().original === null && window.__ws.state().overlays.original === false", 5000) && (await val()) === v3);
    await js("document.querySelector('[data-testid=show-original]').click()");
    check("and shows it again when switched on", await until("window.__ws.state().overlays.original && (window.__ws.state().original?.prims.length ?? 0) > 0", 20000));
    await js("document.querySelector('[data-testid=param-dec]').click()");
    check("a step down shrinks it again", await until(`window.__ws.state().summary.values[${JSON.stringify(param.key)}] < ${v3}`, 60000));
    // the stepping above (up, up, up, down) is ONE undo: it goes back to where the stepping began
    await js("window.__ws.undo()");
    check("a single undo goes back to where the stepping began", await until(`Math.abs(window.__ws.state().summary.values[${JSON.stringify(param.key)}] - ${v0}) < 1e-6`, 60000) && (await sig()) === sig0);
    await js("document.querySelector('[data-testid=param-inc]').click()");
    await until(`window.__ws.state().summary.values[${JSON.stringify(param.key)}] !== ${v0}`, 60000);
    // typing is taken on Enter, not half-typed: the digits on the way change nothing
    const v4 = await val(), revT = await js("window.__ws.state().revision");
    const target = Math.round(param.value * 1.1);
    await js(`(() => { const i = document.querySelector('[data-testid=param-input]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, ${JSON.stringify(String(target))}); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await sleep(600);
    check("a typed number changes nothing until Enter", (await js("window.__ws.state().revision")) === revT && (await val()) === v4);
    await js("document.querySelector('[data-testid=param-input]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))");
    check("Enter takes it and the drawing follows", await until(`Math.abs(window.__ws.state().summary.values[${JSON.stringify(param.key)}] - ${target}) < 1e-6`, 60000), `${param.key} → ${target}`);
    await js(`document.querySelector(${JSON.stringify(row)}).click()`);
    check("a second click closes the editor", await until("!document.querySelector('[data-testid=param-editor]')", 5000));
    await js("window.__ws.state().preview && document.querySelector('[data-testid=tab-values]').click()");
  }

  // 6b2 · the other kind of value opens its editor too: a unit's own named value (the first one the panel lists under the unit's named values)
  if (param) {
    await js("document.querySelector('[data-testid=tab-values]').click()");
    await js(`window.__ws.openUnit(${JSON.stringify(param.unit)})`);
    await until("!!document.querySelector('[data-testid=named-group] [data-testid^=param-]')", 8000);
    const own = await js("document.querySelector('[data-testid=named-group] [data-testid^=param-]')?.dataset.testid || null");
    if (own) {
      await js(`document.querySelector('[data-testid=${JSON.stringify(own).slice(1, -1)}]').click()`);
      check("a unit's own named value opens its editor too", await until("!!document.querySelector('[data-testid=param-editor]')", 60000), own);
      await js(`document.querySelector('[data-testid=${JSON.stringify(own).slice(1, -1)}]').click()`);
      await until("!document.querySelector('[data-testid=param-editor]')", 5000);
    }
  }

  // 6c · what each value IS: named inputs first, readings of work kept as drawn (with the way to unlock it), measured sizes nobody named
  // (kept as drawn on request: the drawing does not change, one click gives them back). Written for the generated fixture, whose part kept as drawn is known.
  if (param && !args.dxf) {
    await js("document.querySelector('[data-testid=tab-values]').click()");
    await js(`window.__ws.openUnit(${JSON.stringify(param.unit)})`);
    await until("!!document.querySelector('[data-testid=named-group]')", 8000);
    const groups = await js(`(() => ({ named: document.querySelectorAll('[data-testid=named-group] [data-testid^=param-]').length,
      generic: !!document.querySelector('[data-testid=generic-group]'), genericOpen: !!document.querySelector('[data-testid=generic-group]')?.open,
      measured: [...document.querySelectorAll('[data-testid^=measured-]')].map((e) => e.dataset.testid.slice(9)).filter((n) => n !== "group"), kept: !!document.querySelector('[data-testid=kept-group]') }))()`);
    check("named values are listed on their own, the unnamed measured sizes are folded away", groups.named > 0 && groups.generic && !groups.genericOpen, JSON.stringify(groups));
    check("work kept as drawn shows its named size as a reading, with the part to unlock", groups.measured.includes("FoundationWidth") && (await js("!!document.querySelector('[data-testid=unlock-FoundationWidth]')")));
    const geometry = async () => JSON.stringify((await (await fetch(`${base}/api/sheet/geometry`)).json()).prims.map((p) => [p.i, p.p, p.m, p.at]));
    const before6c = await geometry();
    const rev6c = await js("window.__ws.state().revision");
    const loose = () => js("document.querySelectorAll('[data-testid=generic-group] [data-testid^=param-]').length");
    const looseBefore = await loose();
    await js("document.querySelector('[data-testid=keep-as-drawn]').click()");
    check("keeping the unnamed sizes as drawn is one step; they move to their own list (the ones a note states stay inputs)",
      (await until("!!document.querySelector('[data-testid=kept-group]')", 20000)) && (await loose()) < looseBefore && (await js("window.__ws.state().revision")) === rev6c + 1,
      `${looseBefore} → ${await loose()} unnamed, revision ${rev6c} → ${await js("window.__ws.state().revision")}`);
    check("and the drawing is exactly what it was", (await geometry()) === before6c);
    const kept = await js("document.querySelectorAll('[data-testid=kept-group] [title]').length");
    await js("document.querySelector('[data-testid=release-all]').click()");
    check("releasing them gives every one back as an input", (await until("!document.querySelector('[data-testid=kept-group]')", 20000)) && (await loose()) === looseBefore, `${kept} were kept`);
    await js("document.querySelector('[data-testid=unlock-FoundationWidth]').click()");
    check("unlocking existing work turns its named size into an input, and moves nothing", await until("!document.querySelector('[data-testid=measured-FoundationWidth]') && !!document.querySelector('[data-testid=param-FoundationWidth]')", 20000)
      && (await geometry()) === before6c);
    // the work is kept on disk as it changes: the badge says when, and the file is there
    check("the page says when the work was last written to disk", await until("/saved \\d/.test(document.querySelector('[data-testid=autosave]')?.textContent || '')", 20000), await js("document.querySelector('[data-testid=autosave]')?.textContent"));
    let saved = [];
    for (let k = 0; k < 50 && !saved.length; k++) {
      try { saved = readdirSync(stateDir).filter((f) => f.endsWith(".autoparam.json") && !f.includes(".prev.")); } catch { /* the folder is made by the first save */ }
      if (!saved.length) await sleep(200);
    }
    check("a project file is kept in the state folder", saved.length > 0, saved.join(", "));
    if (saved.length) {
      const pageRev = await js("window.__ws.state().revision");
      let body = {};
      for (let k = 0; k < 60 && body.revision !== pageRev; k++) {  // the file is written within a couple of seconds of the last change
        try { body = JSON.parse(readFileSync(join(stateDir, saved[0]), "utf8")); } catch { /* being replaced: look again */ }
        if (body.revision !== pageRev) await sleep(250);
      }
      check("it holds the revision the page shows and the unlocked part", body.revision === pageRev && JSON.stringify(body.answers).includes("FoundationWidth"), `file rev ${body.revision}, page rev ${pageRev}`);
    }
  }

  // 6d · a direction the engine could not decide: said, with the ways to settle it — each tried on the sheet — and one chosen (one undo takes it back).
  // Whatever sheet is loaded: the first named value whose growth is undecided; nothing to do (said) where every direction was decided.
  {
    const open = await js(`(async () => {
      const s = window.__ws.state().summary;
      for (const u of s.units.filter((u) => u.parametrized)) {
        const info = await (await fetch('/api/sheet/unit?id=' + encodeURIComponent(u.id))).json();
        for (const p of (info.params || []).filter((p) => p.source === 'ai' && p.kind !== 'level')) {
          const g = (await (await fetch('/api/sheet/param?name=' + encodeURIComponent(p.key))).json()).growth || [];
          if (g.some((r) => r.undecided)) return { key: p.key, name: p.name, unit: u.id };
        }
      }
      return null;
    })()`);
    if (!open) {
      check("every direction of growth was decided on this sheet (nothing to settle)", true);
    } else {
      await js("document.querySelector('[data-testid=tab-values]').click()");
      await js(`window.__ws.openUnit(${JSON.stringify(open.unit)})`);
      await until(`!!document.querySelector('[data-testid=param-${open.name}]')`, 8000);
      await js(`document.querySelector('[data-testid=param-${open.name}]').click()`);
      check("an undecided direction is said, with the way to ask for choices", await until("!!document.querySelector('[data-testid=growth-undecided]') && !!document.querySelector('[data-testid=settle-ways]')", 60000)
        && /Undecided/.test(await js("document.querySelector('[data-testid=growth-undecided]').textContent")), open.key);
      const revWays = await js("window.__ws.state().revision");
      const t0 = Date.now();
      await js("document.querySelector('[data-testid=settle-ways]').click()");
      const offered = await until("document.querySelectorAll('[data-testid=settle-choice]').length > 0 || /Nothing single settles/.test(document.querySelector('[data-testid=settle]')?.textContent || '')", 180000);
      const choices = await js("document.querySelectorAll('[data-testid=settle-choice]').length");
      check("the ways are tried for real and shown, and asking changes nothing", offered && (await js("window.__ws.state().revision")) === revWays, `${choices} way(s) in ${Math.round((Date.now() - t0) / 1000)} s`);
      await shot("04d_ways_to_settle");
      if (choices > 0) {
        const title = await js("document.querySelector('[data-testid=settle-choice] b').textContent");
        check("each way says what it does: which side stays and what stops being an input", /stays|grows equally/.test(await js("document.querySelector('[data-testid=settle-choice]').textContent")) , title);
        await js("document.querySelector('[data-testid=settle-choice] [data-testid=settle-choose]').click()");
        check("choosing one is one step, written as the person's own decision, and the direction is no longer undecided (the size is in the growth, or says it is left out of it)",
          await until(`window.__ws.state().revision === ${revWays} + 1 && !document.querySelector('[data-testid=settle]') && !document.querySelector('[data-testid=growth-undecided]') && (/your choice/.test(document.querySelector('[data-testid=growth-by]')?.textContent || '') || !!document.querySelector('[data-testid=growth-left-out]')) && !!document.querySelector('[data-testid=growth-settled]')`, 120000),
          await js("(document.querySelector('[data-testid=growth-by]')?.textContent || '') + ' | ' + (document.querySelector('[data-testid=growth-left-out]')?.textContent || '')"));
        check("and it is listed among the person's choices, with the way to take it back", await until("!!document.querySelector('[data-testid=settled-group]') || !!document.querySelector('[data-testid=growth-settled]')", 20000));
        await shot("04e_settled");
        await js("window.__ws.undo()");
        check("one undo takes the choice back: undecided again", await until(`!!document.querySelector('[data-testid=growth-undecided]') && window.__ws.state().revision >= ${revWays}`, 60000));
      }
      await js(`document.querySelector('[data-testid=param-${open.name}]').click()`);
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

  // 8 · start clean: the drawing as drawn, the saved work kept aside under a dated name (the last thing here: it forgets the parametrization)
  check("the page offers to start clean when there is saved work", await js("!!document.querySelector('[data-testid=start-clean]')"));
  await js("window.__ws.startClean()");
  check("starting clean shows the drawing as drawn and keeps the saved work aside", await until("window.__ws.state().summary && window.__ws.state().summary.units.every((u) => !u.parametrized)", 60000)
    && readdirSync(stateDir).some((f) => f.includes(".replaced.json")), readdirSync(stateDir).join(", "));

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
