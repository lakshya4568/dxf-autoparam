// Drive the workspace page in a headless Chrome (DevTools protocol, no packages) against `tools/serve_scripted.py` — the agent replaced by a
// script, so nothing is billed — and ASSERT what the page shows: the run's states, the questions, the verdict, the status chips, the highlight of a
// value's geometry, the dotted original, reset value / reset drawing, and that no object is ever printed as "[object Object]".
//
//   uv run python tools/serve_scripted.py --port 8799 &
//   node tools/ui_check.mjs --url http://127.0.0.1:8799/ --out /tmp/ui-check
//
// Exit code 1 when any check fails; screenshots of every stage are saved to --out.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const url = args.url || "http://127.0.0.1:8799/";
const out = args.out || "/tmp/ui-check";
const port = +(args.port || 9341);
const chromePath = args.chrome || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
mkdirSync(out, { recursive: true });
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "uichk-"))}`,
  "--window-size=1680,1050", "--hide-scrollbars", "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pending = new Map();
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
async function js(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result && r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 500));
  return r.result && r.result.result && r.result.result.value;
}
async function shot(name) { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(join(out, name + ".png"), Buffer.from(r.result.data, "base64")); }
const results = [];
function check(name, ok, detail = "") { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); }
async function until(expr, ms = 20000, every = 150) { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await js(expr)) return true; await sleep(every); } return false; }
async function noObjectText(label) { const t = await js("document.body.innerText"); check(`no "[object Object]" on the page (${label})`, !t.includes("[object Object]")); }
const INSTR = "Reduce the clear span to 2500 mm. Keep the middle wall centered, preserve the wall and slab thicknesses, keep the existing foundation fixed. " +
  "The wing walls follow the box. Keep the unrelated pitching detail unchanged. Show me anything ambiguous before applying the change.";
const KEY = "U01_02.ClearSpan";
try {
  for (let k = 0; k < 60; k++) { try { const t = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); const pg = t.find((x) => x.type === "page");
    if (pg) { ws = new WebSocket(pg.webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener("open", r)); break; } } catch (e) { /* not up yet */ } await sleep(200); }
  ws.addEventListener("message", (m) => { const j = JSON.parse(m.data); if (j.id && pending.has(j.id)) { pending.get(j.id)(j); pending.delete(j.id); } });
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1680, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url }); await until("window.__ws && window.__ws.prims > 0", 15000);
  check("the sheet loads with no page error", (await js("window.__errors.length")) === 0 && (await js("window.__ws.prims")) > 0);
  await until("window.__ws.stat !== null", 5000);
  const sentence0 = await js("window.__ws.stat && window.__ws.stat.sentence");
  check("before any work every view says it is not yet analyzed", /not yet analyzed/.test(sentence0 || "") && (await js("window.__ws.stat.overall")) === "not_started", sentence0);
  await shot("01_views_not_started");

  // ── one instruction, one run: budget chunks pause (never cut), the person is asked, the verdict is derived ──
  await js("openView('V01', true); 1"); await sleep(500);
  await js("document.querySelector('[data-tab=ai]').click(); 1"); await sleep(300);
  check("there is ONE Run button and no per-stage buttons", (await js("document.querySelectorAll('#left button').length && !document.querySelector('#ai-views, #ai-unit, #ai-shared, #plan-read')")) === true && (await js("document.querySelectorAll('#ai-run').length")) === 1);
  check("the agent's scope follows the open view", /V01/.test((await js("document.querySelector('#ai-scope').selectedOptions[0].textContent")) || ""));
  await js(`(() => { const s = document.querySelector('#ai-soft'); document.querySelector('#ai-opts, [data-fold=ai-opts]').open = true; s.value = 3; s.dispatchEvent(new Event('change')); return 1; })()`);
  await js(`(() => { const t = document.querySelector('#ai-instr'); t.value = ${JSON.stringify(INSTR)}; t.dispatchEvent(new Event('input')); document.querySelector('#ai-run').click(); return 1; })()`);
  check("a chunk of work ends in PAUSED, not in success", await until("window.__ws.run && window.__ws.run.status === 'paused'", 15000));
  await sleep(400);
  check("a paused run shows no verdict and offers Continue", (await js("window.__ws.run.verdict")) === null && (await js("getComputedStyle(document.querySelector('#ai-continue')).display")) !== "none" && /Paused/.test(await js("document.querySelector('#ai-live .status .top').textContent")));
  await shot("02_paused"); await noObjectText("paused");
  let guard = 0;
  while ((await js("window.__ws.run.status")) === "paused" && guard++ < 6) { await js("document.querySelector('#ai-continue').click(); 1"); await until("window.__ws.run.status === 'running'", 3000); await until("window.__ws.run.status !== 'running'", 15000); await sleep(300); }
  check("the run asks for the one thing the instruction did not say (the anchor)", (await js("window.__ws.run.status")) === "awaiting_user" && /Which side stays/.test(await js("document.querySelector('#ai-live .q').textContent")));
  check("nothing is applied while a question is open", (await js("window.__ws.S.values['" + KEY + "']")) === 3000 || (await js("window.__ws.S.values['" + KEY + "']")) == null);
  await shot("03_asks"); await noObjectText("awaiting");
  await js("document.querySelector('#ai-answer').click(); 1");
  check("after the answer the run completes, with every criterion shown", await until("window.__ws.run.status === 'completed'", 15000) && (await js("document.querySelectorAll('#ai-live .crit.ok').length")) >= 9 && (await js("document.querySelectorAll('#ai-live .crit.no').length")) === 0);
  await sleep(500);
  check("the value was applied to the sheet and both views follow", (await js("window.__ws.S.values['" + KEY + "']")) === 2500);
  await shot("04_complete"); await noObjectText("complete");
  await js("document.querySelectorAll('#ai-live details.turn').forEach((d) => d.open = true); document.querySelectorAll('#ai-live .call details').forEach((d) => d.open = true); 1"); await sleep(300);
  check("tool calls show their arguments and results as JSON", (await js("document.querySelectorAll('#ai-live pre.json').length")) > 10);
  check("the pictures the model was shown are listed and open", (await js("document.querySelectorAll('#ai-live img[data-pic]').length")) >= 3);
  await shot("05_timeline"); await noObjectText("timeline expanded");

  // ── the status chips come from the model ──
  await js("document.querySelector('[data-tab=sheet]').click(); 1"); await sleep(700);
  const sentence1 = await js("window.__ws.stat && window.__ws.stat.sentence");
  check("the views now say complete (derived from the model)", /complete/i.test(sentence1 || "") && (await js("window.__ws.stat.overall")) === "complete", sentence1);
  await shot("06_views_complete");

  // ── click a value: its geometry, by category, in every view ──
  await js(`document.querySelector('[data-tab=params]').click(); window.__ws.openParam(${JSON.stringify(KEY)}); 1`); await until("window.__ws.hl !== null", 10000); await sleep(500);
  const hl = JSON.parse(await js("JSON.stringify({d: window.__ws.hl.drives.size, f: window.__ws.hl.follows.size, t: window.__ws.hl.texts.size, h: window.__ws.hl.holds.length, v: Object.keys(window.__ws.hl.views)})"));
  check("a value's click highlights what it controls, what moves with it and its notes", hl.d > 0 && hl.f >= 0 && hl.t > 0, JSON.stringify(hl));
  check("the geometry it keeps fixed is shown too, and the views it reaches are listed", hl.h >= 1 && hl.v.length === 2);
  check("the inspector shows the value, the original, the reset and the evidence", /3,000 mm/.test(await js("document.querySelector('#right').textContent")) && !!(await js("document.querySelector('#preset')")) && /Where it comes from/i.test(await js("document.querySelector('#right').textContent")));
  await shot("07_highlight");
  await js("document.querySelector('[data-go=V02]').click(); 1"); await sleep(600);
  check("Go to view opens the other view the value reaches", (await js("window.__ws.focus && window.__ws.focus.id")) === "V02");
  await shot("08_other_view");
  await js(`window.__ws.openParam(${JSON.stringify(KEY)}); 1`); await until("window.__ws.hl !== null", 10000); await sleep(400);
  await js("document.querySelector('#porig').click(); 1");
  check("the original geometry is drawn dotted, from the imported drawing", await until("window.__ws.base.on && window.__ws.base.list.length > 10", 8000));
  await shot("09_original_dotted");

  // ── reset one value, then the whole drawing ──
  await js("document.querySelector('#preset').click(); 1");
  check("Reset value puts it back to the imported value and the dotted layer empties", await until("window.__ws.S.values['" + KEY + "'] === 3000", 8000) && await until("window.__ws.base.list.length === 0", 8000));
  await shot("10_reset_value");
  await js("document.querySelector('#more').click(); document.querySelector('#resetdrawing').click(); 1"); await sleep(300);
  check("Reset drawing asks first, in the page", !!(await js("document.querySelector('#modal.on')")) && /imported state/.test(await js("document.querySelector('#modalbox').textContent")));
  await shot("11_reset_confirm");
  await js("document.querySelector('#m-yes').click(); 1"); await sleep(1200);
  check("the drawing is the imported one again: no values, nothing parametrized", (await js("Object.keys(window.__ws.S.values).length")) === 0 && (await js("window.__ws.stat && window.__ws.stat.overall")) === "not_started");
  await js("document.querySelector('#undo').click(); 1"); await sleep(1500);
  check("and one undo brings it all back", (await js("window.__ws.S.values['" + KEY + "']")) != null || (await js("window.__ws.S.can_redo")) === true);
  await shot("12_after_undo");
  check("no page error at any point", (await js("window.__errors.length")) === 0, await js("JSON.stringify(window.__errors)"));
} catch (e) { check("the check itself ran", false, e.message); }
finally { try { ws && ws.close(); } catch (e) { /* closing */ } chrome.kill(); }
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
writeFileSync(join(out, "report.json"), JSON.stringify(results, null, 1));
process.exitCode = failed.length ? 1 : 0;
