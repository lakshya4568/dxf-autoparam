// End to end for Agent Mode: the real engine, the real page, and a SCRIPTED model (tools/serve_scripted.py — no network, no cost, every thought
// marked [scripted]). What the page shows is checked against what the engine reports for the same run, so a tool row that the engine
// never ran, or a status the engine never had, fails here.
//
//   bun run build && node e2e/agent.e2e.mjs [--out DIR] [--port 8800]
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { launch, recorder, requireFreePort, sleep } from "./harness.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "../..");
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? [...a, [v.slice(2), all[i + 1]]] : a), []));
const port = +(args.port || 8800);
const out = args.out || mkdtempSync(join(tmpdir(), "agent-e2e-"));
mkdirSync(out, { recursive: true });
const base = `http://127.0.0.1:${port}`;
const { results, check } = recorder();
const INSTRUCTION = "Reduce the clear span to 2500 mm. Keep the middle wall centered, preserve the wall and slab thicknesses, keep the existing foundation fixed. The wing walls follow the box. Keep the unrelated pitching detail unchanged. Show me anything ambiguous before applying the change.";

await requireFreePort(base);
const server = spawn("uv", ["run", "python", "tools/serve_scripted.py", "--port", String(port), "--delay", "1.2"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let log = "";
server.stdout.on("data", (d) => (log += d));
server.stderr.on("data", (d) => (log += d));
const api = async (path, body) => (await fetch(base + path, body ? { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } } : undefined)).json();

let b = null;
let code = 1;
try {
  for (let k = 0; k < 300; k++) {
    try { if ((await fetch(`${base}/api/sheet`)).ok) break; } catch { await sleep(200); }
    if (k === 299) throw new Error(`the scripted server did not start:\n${log.slice(-1500)}`);
  }
  b = await launch({ port: 9340, out });
  await b.goto(`${base}/`);
  await b.until("window.__ws && window.__ws.state().prims.length && window.__ws.state().fitted && window.__agent", 30000);
  const cam = () => b.js("JSON.stringify(window.__ws.state().cam)");
  const text = (sel) => b.js(`(document.querySelector(${JSON.stringify(sel)}) || {}).textContent || ''`);
  const count = (sel) => b.js(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
  const life = () => b.js("(document.querySelector('[data-testid=life]') || {dataset: {}}).dataset.life || ''");
  const cam0 = await cam();

  // 1 · the dock and its empty state
  await b.click("[data-testid=agent-toggle]");
  check("the Agent dock opens beside the drawing", await b.until("!!document.querySelector('[data-testid=agent-panel]')", 5000));
  check("an empty conversation says what the agent does and offers starting points", (await count("[data-testid=agent-empty]")) === 1);
  check("Send is disabled with nothing typed", await b.js("document.querySelector('[data-testid=send]').disabled"));
  check("the drawing keeps room beside the dock", (await b.js("window.__ws.state().W")) >= 560, `canvas ${await b.js("window.__ws.state().W")} px wide`);
  await b.shot("01_empty");

  // 2 · the paid model is never called before the person accepts its cost
  await b.click("[data-testid=composer-input]");
  await b.type(INSTRUCTION);
  await b.enter();
  check("sending asks about the cost, naming the model", await b.until("!!document.querySelector('[data-testid=cost-confirm]')", 5000), (await text("[data-testid=cost-confirm]")).slice(0, 80));
  await sleep(400);
  check("nothing has started while the question is open", (await api("/api/sheet/ai/runs")).runs.length === 0);
  await b.shot("02_confirm");
  await b.js("[...document.querySelectorAll('[data-testid=cost-confirm] button')].find(x => x.textContent === 'Cancel').click()");
  check("Cancel leaves the draft and starts nothing", (await b.js("document.querySelector('[data-testid=composer-input]').value")) === INSTRUCTION && (await api("/api/sheet/ai/runs")).runs.length === 0);
  await b.click("[data-testid=composer-input]");
  await b.enter();
  await b.until("!!document.querySelector('[data-testid=cost-yes]')", 5000);
  await b.click("[data-testid=cost-yes]");

  // 3 · the run starts once, the page shows it as it is
  check("the run starts and the instruction is the first message", await b.until("!!document.querySelector('[data-testid=user-message]')", 8000), (await text("[data-testid=user-message]")).slice(0, 50));
  check("the composer is emptied and the send control becomes Stop", (await b.js("document.querySelector('[data-testid=composer-input]').value")) === "" && !!(await b.until("!!document.querySelector('[data-testid=stop]')", 5000)));
  await b.click("[data-testid=composer-input]");
  await b.type("a second instruction typed while it works");
  await b.enter();
  await sleep(500);
  check("pressing Enter while it works does not start a second run", (await api("/api/sheet/ai/runs")).runs.length === 1);
  check("the status says what the run is doing, from the engine", /^(starting|planning|inspecting|tool|thinking|applying|validating)$/.test(await life()), `life=${await life()}`);
  await b.until("document.querySelectorAll('[data-testid=activity]').length > 0 && document.querySelector('[data-testid=activity]').textContent.includes('call')", 20000);
  check("compact: the activity is one folded line with the latest tool names", (await count("[data-testid=activity-body]")) === 0 && (await text("[data-testid=activity]")).length > 0, (await text("[data-testid=activity]")).slice(0, 90));
  await b.shot("03_live_compact");

  // 4 · verbose opens the same data
  await b.click("[data-testid=mode-verbose]");
  check("verbose: the timeline opens, grouped by stage, with tool rows", await b.until("!!(document.querySelector('[data-testid=activity-body]') && document.querySelector('[data-testid=phase]') && document.querySelector('[data-testid=tool-row]'))", 8000));
  await b.shot("04_live_verbose");
  await b.click("[data-testid=mode-compact]");
  check("compact again folds it", await b.until("!document.querySelector('[data-testid=activity-body]')", 5000));
  await b.click("[data-testid=mode-verbose]");

  // 5 · the run asks the person (the anchor was not said)
  check("the run waits for the person's decision", await b.until("!!document.querySelector('[data-testid=questions]')", 90000));
  check("the status says it is waiting, and nothing is spinning", (await life()) === "awaiting" && (await count("[data-testid=life] .animate-spin")) === 0);
  const events = (await api("/api/sheet/ai/progress?run=R1&since=0")).events;
  const engineTools = events.filter((e) => e.kind === "tool");
  const rows = await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].map(r => ({ name: r.dataset.tool, state: r.dataset.state }))");
  check("every tool row is a call the engine really made (names)", rows.length > 0 && rows.every((r) => events.some((e) => e.kind === "tool_start" && e.name === r.name)), `${rows.length} rows`);
  check("there is a row for every call the engine announced", rows.length === events.filter((e) => e.kind === "tool_start").length, `${rows.length} rows, ${events.filter((e) => e.kind === "tool_start").length} announced`);
  check("failed calls are shown failed, completed ones completed", rows.filter((r) => r.state === "failed").length === engineTools.filter((e) => e.ok === false).length && rows.filter((r) => r.state === "done").length === engineTools.filter((e) => e.ok !== false).length,
    `${rows.filter((r) => r.state === "failed").length} failed, ${rows.filter((r) => r.state === "done").length} done`);
  check("no call is shown running or queued while the run waits", rows.every((r) => r.state !== "running" && r.state !== "queued"));
  await b.shot("05_awaiting");
  const failedRow = rows.findIndex((r) => r.state === "failed");
  if (failedRow >= 0) {
    await b.js(`document.querySelectorAll('[data-testid=tool-row]')[${failedRow}].scrollIntoView({block:'center'})`);
    check("a failed call says why without being opened", (await b.js(`document.querySelectorAll('[data-testid=tool-row]')[${failedRow}].textContent.length`)) > 20);
  }

  // 6 · answer; the run finishes and the drawing reflects the change
  const rev0 = await b.js("window.__ws.state().revision");
  await b.click("[data-testid=answer-send]");
  check("the run goes on after the answer", await b.until("['thinking','inspecting','tool','applying','validating','planning','starting'].includes(document.querySelector('[data-testid=life]').dataset.life)", 8000));
  check("the answer is a message of its own", await b.until("document.querySelectorAll('[data-testid=user-message]').length === 2", 8000));
  check("the run completes", await b.until("document.querySelector('[data-testid=life]').dataset.life === 'completed'", 60000), `life=${await life()}`);
  check("the result is shown with its state", (await count("[data-testid=result][data-state=completed]")) === 1, (await text("[data-testid=result]")).slice(0, 80));
  check("nothing is left running or queued", (await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].filter(r => ['running','queued'].includes(r.dataset.state)).length")) === 0 && (await count("[data-testid=life] .animate-spin")) === 0);
  await b.until("window.__ws.state().revision > " + rev0, 10000);
  const rev1 = await b.js("window.__ws.state().revision");
  const engineRev = (await api("/api/sheet")).revision;
  check("the drawing follows the engine's revision", rev1 > rev0 && rev1 === engineRev, `revision ${rev0} → ${rev1} (engine ${engineRev})`);
  check("the camera did not move during the whole run", (await cam()) === cam0);
  await b.shot("06_completed_verbose");

  // 7 · a follow-up continues the conversation, and Stop ends it cleanly
  await b.click("[data-testid=composer-input]");
  await b.js("document.querySelector('[data-testid=composer-input]').select()");
  await b.type("Now do it again for a different span");
  await b.enter();
  check("the follow-up starts a second run that follows the first", await b.until("!!document.querySelector('[data-testid=stop]')", 8000) && (await api("/api/sheet/ai/progress?run=R2&since=0")).parent === "R1");
  await b.until("document.querySelectorAll('[data-testid=tool-row]').length > " + rows.length, 20000);
  await b.click("[data-testid=stop]");
  check("stopping ends the run as stopped", await b.until("document.querySelector('[data-testid=life]').dataset.life === 'cancelled'", 20000), `life=${await life()}`);
  check("the engine agrees", (await api("/api/sheet/ai/progress?run=R2&since=0")).status === "stopped");
  check("no call is shown as still running after the stop", (await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].filter(r => ['running','queued'].includes(r.dataset.state)).length")) === 0);
  check("a stopped run can be continued", !!(await b.until("!!document.querySelector('[data-testid=resume]')", 5000)));
  await b.shot("07_stopped");

  // 8 · the conversation survives a reload (it is the engine's record, not the page's memory)
  await b.goto(`${base}/`);
  await b.until("window.__agent && window.__ws && window.__ws.state().prims.length", 30000);
  await b.js("document.querySelector('[data-testid=agent-toggle]').click()");
  check("after a reload the conversation is rebuilt from the engine's events", await b.until("document.querySelectorAll('[data-testid=user-message]').length === 3", 15000), `${await count("[data-testid=user-message]")} messages from the person`);
  check("and the stopped run still reads as stopped", (await life()) === "cancelled");

  // 9 · themes
  await b.js("[...document.querySelectorAll('header button')].find(x => x.textContent === 'Dark' || x.textContent === 'Light').click()");
  await sleep(200);
  await b.shot("08_other_theme");

  const errors = await b.js("window.__errors");
  check("no uncaught errors in the page", errors.length === 0, errors.slice(0, 3).join(" | "));
  code = results.every((r) => r.ok) ? 0 : 1;
} catch (e) {
  console.error(e);
  check("the e2e ran to the end", false, String(e).slice(0, 300));
} finally {
  writeFileSync(join(out, "agent-e2e.json"), JSON.stringify({ results }, null, 1));
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} passed · screenshots in ${out}`);
  b?.close();
  server.kill("SIGTERM");
  await sleep(300);
  process.exit(code);
}
