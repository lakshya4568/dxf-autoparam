// The agent's work, folded. Collapsed it is one line (what it is doing now, or what it did) and the names of its latest tools;
// opened it is the chronological record, grouped by stage: tool calls, the model's own summaries of its thinking (never its raw
// reasoning), what the engine applied, notices, errors. Compact keeps technical details shut; verbose opens them — the same data.
import { useStore } from "../state/store";
import { agent, toggleFold } from "../state/agent";
import { Prose } from "./Inline";
import { countCalls, currentCall, latestFinding, type AgentMessage, type Group, type Item, type Life, type Tone } from "./model";
import { Spinner, ToolMark } from "./StatusMark";
import { ToolRow } from "./ToolRow";

const TONE: Record<Tone, string> = {
  info: "text-slate-500 dark:text-slate-400",
  ok: "text-emerald-700 dark:text-emerald-400",
  warn: "text-amber-700 dark:text-amber-400",
  bad: "text-red-700 dark:text-red-400",
};

function useFold(key: string, dflt: boolean): [boolean, () => void] {
  const stored = useStore(agent, (s) => s.folds[key]);
  const open = stored ?? dflt;
  return [open, () => toggleFold(key, open)];
}

function Thought({ itemKey, text, verbose }: { itemKey: string; text: string; verbose: boolean }) {
  const [open, toggle] = useFold(itemKey, verbose);
  const words = text.split(/\s+/).filter(Boolean).length;
  return (
    <div className="py-0.5" data-testid="thought">
      <button className="flex items-center gap-1 text-[12px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" onClick={toggle} aria-expanded={open}>
        <span className={`text-[10px] transition-transform ${open ? "rotate-90" : ""}`}>›</span>Reasoning summary <span className="text-slate-400">· {words} words</span>
      </button>
      {open && <Prose text={text} className="ml-3 mt-0.5 border-l border-slate-200 dark:border-slate-700 pl-2 text-[12px] text-slate-600 dark:text-slate-300" />}
    </div>
  );
}

function ItemView({ item, k, runId, verbose }: { item: Item; k: string; runId: string; verbose: boolean }) {
  const [open, toggle] = useFold(k, verbose || (item.type === "tool" && item.call.state === "failed"));
  switch (item.type) {
    case "tool":
      return <ToolRow call={item.call} runId={runId} open={open} onToggle={toggle} />;
    case "thought":
      return <Thought itemKey={k} text={item.text} verbose={verbose} />;
    case "notice":
      return (
        <div className={`py-0.5 text-[12px] break-words ${TONE[item.tone]}`} data-testid="notice" data-tone={item.tone}>
          {item.text}
          {item.detail && verbose && <div className="text-[11px] text-slate-400">{item.detail}</div>}
        </div>
      );
    case "applied":
      return <div className="py-0.5 text-[12px] text-emerald-700 dark:text-emerald-400" data-testid="applied">✓ {item.text}</div>;
    case "picture":
      return <div className="py-0.5 text-[12px] text-slate-500">▣ {item.text}</div>;
    case "budget":
      return verbose ? <div className="py-0.5 text-[11px] text-slate-400">{item.text}</div> : null;
  }
}

function GroupView({ g, runId, verbose, last }: { g: Group; runId: string; verbose: boolean; last: boolean }) {
  const tools = g.items.filter((i): i is Extract<Item, { type: "tool" }> => i.type === "tool");
  const failed = tools.filter((t) => t.call.state === "failed").length;
  return (
    <section className="mt-2 first:mt-0" data-testid="phase" data-stage={g.stage}>
      <h4 className="flex items-baseline gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {g.stage}
        <span className="font-normal normal-case tracking-normal">{tools.length ? `${tools.length} call${tools.length === 1 ? "" : "s"}` : ""}{failed ? ` · ${failed} failed` : ""}</span>
      </h4>
      <div className="mt-0.5 border-l border-slate-200 dark:border-slate-700 pl-2.5">
        {g.items.map((it, i) => <ItemView key={`${g.key}/${i}`} k={`${g.key}/${i}`} item={it} runId={runId} verbose={verbose} />)}
        {last && tools.length === 0 && g.items.length === 0 && <div className="text-[12px] text-slate-400">…</div>}
      </div>
    </section>
  );
}

export function ActivityBlock({ m, life, verbose }: { m: AgentMessage; life: Life | null; verbose: boolean }) {
  const live = !!life?.active && m.last;
  const [open, toggle] = useFold(`${m.key}/activity`, verbose);
  const c = countCalls(m);
  const running = currentCall(m);
  const recent = m.groups.flatMap((g) => g.items).filter((i): i is Extract<Item, { type: "tool" }> => i.type === "tool").slice(-4);
  const empty = c.calls === 0 && m.groups.every((g) => g.items.length === 0);
  let title: string;
  const calls = `${c.calls} tool call${c.calls === 1 ? "" : "s"}`;
  if (live) title = life!.label;
  else if (m.ended?.to === "stopped") title = c.calls ? `Stopped after ${calls}` : "Stopped before any tool call";
  else if (m.ended?.to === "failed") title = c.calls ? `Failed after ${calls}` : "Failed before any tool call";
  else if (m.ended?.to === "paused" || m.ended?.to === "exhausted") title = c.calls ? `Paused after ${calls}` : "Paused";
  else if (m.ended?.to === "awaiting_user") title = c.calls ? `Worked through ${calls}, then asked you` : "Asked you";
  else if (m.ended) title = c.calls ? `Worked through ${calls}` : "Finished without tool calls";
  else title = c.calls ? calls : "Activity";
  const finding = latestFinding(m);
  if (empty && !live) return null;
  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-700/80" data-testid="activity" data-open={open} data-live={live}>
      <button className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left" onClick={toggle} aria-expanded={open}>
        {live ? <Spinner /> : <span className={`text-[10px] text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}>›</span>}
        <span className="text-[13px] font-medium">{title}</span>
        {live && life!.detail && <span className="min-w-0 flex-1 truncate text-[12px] text-slate-500 dark:text-slate-400">{life!.detail}</span>}
        {!live && <span className="flex-1" />}
        <span className="shrink-0 text-[11px] text-slate-400 num">
          {c.calls ? `${c.calls} call${c.calls === 1 ? "" : "s"}` : ""}{c.failed ? ` · ${c.failed} failed` : ""}
        </span>
        {live && <span className="sr-only">{running?.name}</span>}
      </button>
      {!open && recent.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-2.5 pb-1.5 -mt-0.5">
          {recent.map((t, i) => (
            <span key={`${t.call.id}-${i}`} className="inline-flex items-center gap-1 text-[11px] text-slate-500" title={t.call.summary || t.call.doing}>
              <ToolMark state={t.call.state} /><code>{t.call.name}</code>
            </span>
          ))}
          {live && finding && <span className="min-w-0 basis-full truncate text-[11px] text-slate-400">Last: {finding}</span>}
        </div>
      )}
      {open && (
        <div className="border-t border-slate-200 dark:border-slate-700/80 px-2.5 py-2" data-testid="activity-body">
          {m.groups.map((g, i) => <GroupView key={g.key} g={g} runId={m.runId} verbose={verbose} last={i === m.groups.length - 1} />)}
          {live && m.groups.length === 0 && <div className="text-[12px] text-slate-400">Waiting for the first event…</div>}
        </div>
      )}
    </div>
  );
}
