// Shared by the browser tests: a headless Chrome driven over the DevTools protocol (no framework, no download) and a check recorder.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function recorder() {
  const results = [];
  return {
    results,
    check(name, ok, detail = "") {
      results.push({ name, ok: !!ok, detail });
      console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
    },
  };
}

export async function launch({ port, width = 1500, height = 950, out, chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" }) {
  const profile = mkdtempSync(join(tmpdir(), "ws-e2e-chrome-"));
  const proc = spawn(chrome, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", `--window-size=${width},${height}`, "about:blank"], { stdio: "ignore" });
  let targets;
  for (let k = 0; k < 100 && !targets; k++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { await sleep(150); }
  }
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(m.error.message)) : p.res(m.result);
    }
  });
  const send = (method, params = {}) => {
    const n = ++id;
    ws.send(JSON.stringify({ id: n, method, params }));
    return new Promise((res, rej) => pending.set(n, { res, rej }));
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__errors=[];addEventListener('error',e=>__errors.push(String(e.message)));addEventListener('unhandledrejection',e=>__errors.push(String(e.reason)));" });
  const js = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const until = async (expr, ms = 20000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const v = await js(expr).catch(() => null);
      if (v) return v;
      await sleep(80);
    }
    return null;
  };
  return {
    send, js, until,
    goto: (url) => send("Page.navigate", { url }),
    async shot(name) {
      const r = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(out, `${name}.png`), Buffer.from(r.data, "base64"));
    },
    async type(text) { await send("Input.insertText", { text }); },
    async key(key, code = key, vk = 0, text) {
      await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: vk, ...(text ? { text } : {}) });
      await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk });
    },
    async enter() { await this.key("Enter", "Enter", 13, "\r"); },
    async click(selector) {
      const box = await js(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
      if (!box) throw new Error(`nothing to click: ${selector}`);
      for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
        await send("Input.dispatchMouseEvent", { type, x: box.x, y: box.y, button: "left", buttons: type === "mouseReleased" ? 0 : 1, clickCount: 1 });
    },
    close() {
      try { ws.close(); } catch { /* already closed */ }
      proc.kill("SIGTERM");
      try { rmSync(profile, { recursive: true, force: true }); } catch { /* best effort */ }
    },
  };
}

/** A test must talk to the server it started, not to one already listening (that is a different drawing): refuse to start if the port answers. */
export async function requireFreePort(base) {
  let answered = false;
  try { answered = (await fetch(`${base}/api/sheet`, { signal: AbortSignal.timeout(1500) })).status > 0; } catch { /* nothing listens: good */ }
  if (answered) throw new Error(`something already answers on ${base}: stop it, or pass --port`);
}
