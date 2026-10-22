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
  // what the person sees: two corners of the drawing in the window, and the zoom. A panel opening beside the canvas changes the camera state (the
  // world point at the canvas centre) and keeps the drawing where it is on the screen — that is not the camera moving
  const view = () => b.js("(() => { const s = window.__ws.state(); const e = s.summary.extent; return [window.__ws.windowPoint(e[0], e[1]), window.__ws.windowPoint(e[2], e[3]), s.cam.s, s.cam.rot]; })()");
  const sameView = (a, c) => a.slice(0, 2).every((p, i) => Math.abs(p[0] - c[i][0]) < 0.5 && Math.abs(p[1] - c[i][1]) < 0.5) && Math.abs(a[2] - c[2]) <= 1e-12 * a[2] && a[3] === c[3];
  const text = (sel) => b.js(`(document.querySelector(${JSON.stringify(sel)}) || {}).textContent || ''`);
  const count = (sel) => b.js(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
  const life = () => b.js("(document.querySelector('[data-testid=life]') || {dataset: {}}).dataset.life || ''");
  const view0 = await view();

  // 1 · the dock and its empty state
  await b.click("[data-testid=agent-toggle]");
  check("the Agent dock opens beside the drawing", await b.until("!!document.querySelector('[data-testid=agent-panel]')", 5000));
  check("an empty conversation says what the agent does and offers starting points", (await count("[data-testid=agent-empty]")) === 1);
  check("Send is disabled with nothing typed", await b.js("document.querySelector('[data-testid=send]').disabled"));
  check("the drawing keeps room beside the dock", (await b.js("window.__ws.state().W")) >= 560, `canvas ${await b.js("window.__ws.state().W")} px wide`);
  await b.shot("01_empty");

  // 2 · the paid model is never called before the person accepts its cost. The model list comes first (Send needs a model; the server may wait a
  // few seconds for a gateway's catalogue — a slow or busy one is not this page's failure)
  check("the model picker names a model", await b.until("!!document.querySelector('[data-testid=model]')?.value", 20000), await b.js("document.querySelector('[data-testid=model]')?.value || ''"));
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
  await b.type("Look at the section first.");
  await b.enter();
  await sleep(500);
  check("pressing Enter while it works says it to the agent and does not start a second run", (await api("/api/sheet/ai/runs")).runs.length === 1);
  check("the note is the engine's record and a message of the person's, marked as a note", await b.until("[...document.querySelectorAll('[data-testid=user-message]')].some(x => /Note while it works/.test(x.textContent) && /Look at the section first/.test(x.textContent))", 8000)
    && (await api("/api/sheet/ai/progress?run=R1&since=0")).events.some((e) => e.kind === "user" && e.while_working && e.text === "Look at the section first."));
  check("the box is emptied once the engine has the note", (await b.js("document.querySelector('[data-testid=composer-input]').value")) === "");
  check("the status says what the run is doing, from the engine", /^(starting|planning|inspecting|tool|thinking|applying|validating)$/.test(await life()), `life=${await life()}`);
  await b.until("document.querySelectorAll('[data-testid=tool-row]').length > 0", 20000);
  check("there is no Compact / Verbose switch: one standard view", (await count("[data-testid=mode-compact]")) + (await count("[data-testid=mode-verbose]")) === 0);
  check("while it works the activity is open: a progress line, then the tools it used", (await count("[data-testid=activity-body]")) === 1 && (await count("[data-testid=progress]")) > 0 && (await count("[data-testid=tool-row]")) > 0, (await text("[data-testid=progress]")).slice(0, 80));
  check("a tool entry is its name and nothing else — no input, no output", await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].every(r => r.textContent.replace(/[✓✗○–]/g, '').trim() === r.dataset.tool)") && !(await b.js("/\\b(Input|Output)\\b/.test(document.querySelector('[data-testid=activity-body]').innerText)")));
  check("the thinking is a section of its own, shut by default", (await count("[data-testid=thinking]")) === 1 && (await b.js("document.querySelector('[data-testid=thinking]').dataset.open")) === "false" && (await count("[data-testid=thinking-body]")) === 0);
  await b.shot("03_live");

  // 4 · the thinking opens on demand and shuts again
  await b.click("[data-testid=thinking] button");
  check("opening the thinking shows the agent's summaries turn by turn", await b.until("!!document.querySelector('[data-testid=thinking-body]') && /Turn 1/.test(document.querySelector('[data-testid=thinking-body]').textContent)", 5000), (await text("[data-testid=thinking-body]")).slice(0, 80));
  await b.shot("04_thinking_open");
  await b.click("[data-testid=thinking] button");
  check("and it shuts again", await b.until("!document.querySelector('[data-testid=thinking-body]')", 5000));

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
  check("a failed call is marked failed and is still only its name", rows.filter((r) => r.state === "failed").length === 0 || await b.js("[...document.querySelectorAll('[data-testid=tool-row][data-state=failed]')].every(r => r.textContent.replace(/[✓✗○–]/g, '').trim() === r.dataset.tool)"));
  check("the question is multiple choice: options, the recommended one marked, and a way to answer in words", (await count("[data-testid=option]")) >= 2 && (await count("[data-testid=questions] input[aria-label='in your own words']")) >= 1);

  // 6 · answer; the run finishes and the drawing reflects the change
  const rev0 = await b.js("window.__ws.state().revision");
  await b.click("[data-testid=answer-send]");
  check("the run goes on after the answer", await b.until("['thinking','inspecting','tool','applying','validating','planning','starting'].includes(document.querySelector('[data-testid=life]').dataset.life)", 8000));
  check("the answer is a message of its own", await b.until("document.querySelectorAll('[data-testid=user-message]').length === 3", 8000));
  check("the run completes", await b.until("document.querySelector('[data-testid=life]').dataset.life === 'completed'", 60000), `life=${await life()}`);
  check("the result is shown with its state", (await count("[data-testid=result][data-state=completed]")) === 1, (await text("[data-testid=result]")).slice(0, 80));
  check("the result leads with the engine's word, then the agent's summary, and keeps the checks under Details", /^Complete/.test(await text("[data-testid=result]")) && (await count("[data-testid=result-details]")) === 1 && (await b.js("document.querySelector('[data-testid=result-details]').open")) === false);
  check("once the work has ended the activity folds into one line", (await b.js("document.querySelector('[data-testid=activity]').dataset.open")) === "false" && (await count("[data-testid=activity-body]")) === 0);
  check("nothing is left running or queued", (await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].filter(r => ['running','queued'].includes(r.dataset.state)).length")) === 0 && (await count("[data-testid=life] .animate-spin")) === 0);
  await b.until("window.__ws.state().revision > " + rev0, 10000);
  const rev1 = await b.js("window.__ws.state().revision");
  const engineRev = (await api("/api/sheet")).revision;
  check("the drawing follows the engine's revision", rev1 > rev0 && rev1 === engineRev, `revision ${rev0} → ${rev1} (engine ${engineRev})`);
  check("the drawing did not move on the screen during the whole run (the dock opening included)", sameView(view0, await view()), JSON.stringify(await view()));
  await b.shot("06_completed");

  // 6b · the pictures the agent was given: a gallery with what the engine says of each, and one shown large
  const given = [...new Map((await api("/api/sheet/ai/progress?run=R1&since=0")).events.filter((e) => e.kind === "image").map((e) => [e.id, e])).values()];
  check("the engine told the page of every picture it gave the model, with what each is", given.length >= 2 && given.every((e) => e.pic && e.pic.kind && e.pic.size && e.pic.caption !== undefined), `${given.length} pictures: ${given.map((e) => e.pic?.kind).join(", ")}`);
  check("the header counts them", (await text("[data-testid=pictures-toggle]")).replace(/\s+/g, "").endsWith(String(given.length)), await text("[data-testid=pictures-toggle]"));
  await b.click("[data-testid=pictures-toggle]");
  check("the gallery opens over the thread with one card per picture", await b.until(`document.querySelectorAll('[data-testid=gallery-item]').length === ${given.length}`, 5000), `${await count("[data-testid=gallery-item]")} cards`);
  check("the thumbnails are the engine's pictures (they load)", await b.until("[...document.querySelectorAll('[data-testid=gallery-item] img')].filter(i => i.getBoundingClientRect().top < innerHeight).every(i => i.complete && i.naturalWidth > 0) && document.querySelectorAll('[data-testid=gallery-item] img').length > 0", 15000));
  check("each card says what it is, its turn and whether the text could be read", await b.js("[...document.querySelectorAll('[data-testid=gallery-item]')].every(c => /IMG\\d+/.test(c.textContent) && /(turn \\d+|at the start)/.test(c.textContent))"));
  await b.shot("06b_gallery");
  const firstId = await b.js("document.querySelector('[data-testid=gallery-item]').dataset.id");
  await b.click("[data-testid=gallery-item]");
  check("a picture opens large, as a dialog", await b.until(`!!document.querySelector('[data-testid=lightbox][role=dialog][aria-modal=true][data-id="${firstId}"]')`, 5000));
  check("the large picture loads and its metadata is the engine's", await b.until("(() => { const i = document.querySelector('[data-testid=lightbox-image]'); return !!i && i.complete && i.naturalWidth > 0; })()", 15000) && /per pixel/.test(await text("[data-testid=lightbox-info]")) && (await text("[data-testid=lightbox-info]")).includes(firstId), (await text("[data-testid=lightbox-info]")).slice(0, 120));
  check("a picture of the sheet before the run changed it says so", given[0].revision < (await b.js("window.__ws.state().revision")) ? /older drawing/.test(await text("[data-testid=lightbox-info]")) : true, await text("[data-testid=lightbox-stale]"));
  await b.shot("06c_lightbox");
  await b.key("ArrowRight", "ArrowRight", 39);
  check("the arrow keys move between pictures", await b.until(`document.querySelector('[data-testid=lightbox]')?.dataset.id !== "${firstId}"`, 3000), await b.js("document.querySelector('[data-testid=lightbox]')?.dataset.id"));
  check("the canvas did not pan behind the picture", sameView(view0, await view()));
  await b.key("Escape", "Escape", 27);
  check("Escape closes the picture and focus returns to its card", await b.until("!document.querySelector('[data-testid=lightbox]')", 3000) && (await b.js("document.activeElement?.dataset?.testid")) === "gallery-item");
  await b.click("[data-testid=gallery-close]");
  check("the gallery closes and the thread is where it was", await b.until("!document.querySelector('[data-testid=gallery]')", 3000) && (await count("[data-testid=thread]")) === 1);
  check("the activity carries no picture lines: pictures are the gallery's", (await count("[data-testid=picture-item]")) === 0);

  // 7 · a follow-up continues the conversation: a QUESTION about the drawing, which the agent answers with multiple-choice questions of its own
  await b.click("[data-testid=composer-input]");
  await b.js("document.querySelector('[data-testid=composer-input]').select()");
  await b.type("Ask me which view holds the shared value.");
  await b.enter();
  check("the follow-up starts a second run that follows the first", await b.until("!!document.querySelector('[data-testid=stop]')", 8000) && (await api("/api/sheet/ai/progress?run=R2&since=0")).parent === "R1");
  check("the agent asks two multiple-choice questions", await b.until("document.querySelectorAll('[data-testid=question]').length === 2", 90000), `${await count("[data-testid=question]")} questions`);
  check("each has its header, what each option means, and the recommended one is marked and chosen", (await count("[data-testid=question-header]")) === 2 && /the half section/.test(await text("[data-testid=questions]")) && /\(recommended\)/.test(await text("[data-testid=questions]"))
    && (await b.js("document.querySelector('[data-testid=question] input[type=radio]:checked')?.parentElement.textContent.includes('Section')")));
  check("a question where several choices apply has checkboxes", (await count("[data-testid=question][data-multi=true] input[type=checkbox]")) === 3);
  check("an answer is needed on every question", await b.js("document.querySelector('[data-testid=answer-send]').disabled"), "nothing ticked on the second question yet");
  await b.shot("07a_questions");
  await b.js("(() => { const boxes = document.querySelectorAll('[data-testid=question][data-multi=true] input[type=checkbox]'); boxes[0].click(); boxes[2].click(); })()");
  check("ticking enables the answer", await b.until("!document.querySelector('[data-testid=answer-send]').disabled", 3000));
  await b.click("[data-testid=answer-send]");
  check("the question-only run completes without parametrizing a single unit", await b.until("document.querySelector('[data-testid=life]').dataset.life === 'completed'", 60000), `life=${await life()}`);
  const r2 = (await api("/api/sheet/ai/progress?run=R2&since=0")).events;
  const chosen = r2.find((e) => e.kind === "user" && e.answers);
  check("the engine got the choices: one option, and the several ticked joined", !!chosen && Object.values(chosen.answers).includes("Section") && Object.values(chosen.answers).includes("Clear span | Slab thickness"), JSON.stringify(chosen?.answers));
  check("the result is the agent's answer, led by the engine's word", /^Complete/.test(await text("[data-testid=result]")) && /I used your choices/.test(await text("[data-testid=result]")));
  await b.shot("07b_answered");

  // 7c · a third instruction: Stop ends it cleanly
  await b.click("[data-testid=composer-input]");
  await b.js("document.querySelector('[data-testid=composer-input]').select()");
  await b.type("Now do it again for a different span");
  await b.enter();
  check("the next instruction starts a third run that follows the second", await b.until("!!document.querySelector('[data-testid=stop]')", 8000) && (await api("/api/sheet/ai/progress?run=R3&since=0")).parent === "R2");
  await b.until("document.querySelectorAll('[data-testid=tool-row]').length > 0", 20000);
  await b.click("[data-testid=stop]");
  check("stopping ends the run as stopped", await b.until("document.querySelector('[data-testid=life]').dataset.life === 'cancelled'", 20000), `life=${await life()}`);
  check("the engine agrees", (await api("/api/sheet/ai/progress?run=R3&since=0")).status === "stopped");
  check("no call is shown as still running after the stop", (await b.js("[...document.querySelectorAll('[data-testid=tool-row]')].filter(r => ['running','queued'].includes(r.dataset.state)).length")) === 0);
  check("a stopped run can be continued", !!(await b.until("!!document.querySelector('[data-testid=resume]')", 5000)));
  await b.shot("07_stopped");

  // 8 · the conversation survives a reload (it is the engine's record, not the page's memory)
  await b.goto(`${base}/`);
  await b.until("window.__agent && window.__ws && window.__ws.state().prims.length", 30000);
  await b.js("document.querySelector('[data-testid=agent-toggle]').click()");
  check("after a reload the conversation is rebuilt from the engine's events", await b.until("document.querySelectorAll('[data-testid=user-message]').length === 6", 15000), `${await count("[data-testid=user-message]")} messages from the person`);
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
