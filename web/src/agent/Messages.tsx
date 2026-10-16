// The conversation's messages: what the person said (with where it applies), what the agent did (its folded activity, then — when the
// work has ended — its result: the engine's headline, the model's own summary, the criteria it checked, what it applied), a pending
// decision, and the actions that make sense for the run's state.
import { useStore } from "../state/store";
import { agent, applyHeld, currentRun, requestResume, revert } from "../state/agent";
import { fitView } from "../state/workspace";
import { ActivityBlock } from "./Activity";
import { Prose } from "./Inline";
import type { AgentMessage, EarlierRun, Life, UserMessage } from "./model";
import { questionsOf, STATE_WORDS, verdictOf } from "./model";
import { Questions } from "./Questions";

function scopeText(scope: Record<string, unknown> | undefined): string {
  if (!scope) return "";
  const kind = String(scope.kind ?? "");
  if (kind === "drawing") return "whole drawing";
  if (kind === "selection") return `selection of ${Array.isArray(scope.entities) ? scope.entities.length : "?"} entit${Array.isArray(scope.entities) && scope.entities.length === 1 ? "y" : "ies"}`;
  if (kind === "view" || (Array.isArray(scope.views) && scope.views.length)) return `view ${(scope.views as string[] | undefined)?.join(", ") ?? ""}`;
  if (kind === "param") return `value ${String(scope.param ?? "")}`;
  return kind === "drawing" ? "whole drawing" : "";
}

export function UserBubble({ m }: { m: UserMessage }) {
  const where = scopeText(m.scope);
  const answered = m.answers ? Object.keys(m.answers).length : 0;
  return (
    <div className="flex flex-col items-end" data-testid="user-message">
      <div className="max-w-[92%] rounded-lg bg-slate-100 dark:bg-slate-800 px-3 py-2 text-[13px]">
        {m.text ? <Prose text={m.text} /> : <span className="text-slate-500">Answered {answered} question{answered === 1 ? "" : "s"}</span>}
        {m.text && answered > 0 && <div className="mt-1 text-[11px] text-slate-500">and answered {answered} question{answered === 1 ? "" : "s"}</div>}
      </div>
      {where && (
        <button className="mt-0.5 text-[11px] text-slate-400 hover:underline" onClick={() => { const v = (m.scope?.views as string[] | undefined)?.[0]; if (v) fitView(v); }}>
          {where}
        </button>
      )}
    </div>
  );
}

export function EarlierBubble({ m }: { m: EarlierRun }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 dark:border-slate-700 px-2.5 py-1.5 text-[12px] text-slate-500" data-testid="earlier-run" title={m.instruction}>
      <span className="font-mono mr-1">{m.runId}</span>{m.label}
      <div className="truncate">{m.instruction}</div>
      {m.headline && <div className="truncate text-slate-400">{m.headline}</div>}
      <div className="text-[11px] text-slate-400">Saved with the project — its step-by-step record is not kept.</div>
    </div>
  );
}

function Result({ m }: { m: AgentMessage }) {
  const run = useStore(agent, (s) => currentRun(s));
  const v = verdictOf(run);
  const state = m.ended?.to;
  if (!state || state === "awaiting_user") return null; // a question is the decision card, not a result
  const tone = state === "completed" ? "text-emerald-700 dark:text-emerald-400" : state === "failed" ? "text-red-700 dark:text-red-400" : "text-amber-700 dark:text-amber-400";
  return (
    <div className="text-[13px]" data-testid="result" data-state={state}>
      <div className={`font-medium ${tone}`}>{STATE_WORDS[state] ?? state}</div>
      {v?.headline && <div>{v.headline}</div>}
      {v?.finish_summary && <details className="mt-1"><summary className="cursor-pointer text-[12px] text-slate-500">What the model says it did</summary><Prose text={v.finish_summary} className="mt-1 text-[12px]" /></details>}
      {v?.criteria && v.criteria.length > 0 && (
        <details className="mt-1" open={state !== "completed"}>
          <summary className="cursor-pointer text-[12px] text-slate-500">{v.criteria.filter((c) => c.ok).length} of {v.criteria.length} checks hold</summary>
          <ul className="mt-1">
            {v.criteria.map((c) => (
              <li key={c.id} className={`text-[12px] ${c.ok ? "" : "text-red-700 dark:text-red-300"}`}>{c.ok ? "✓" : "✗"} {c.id.replace(/_/g, " ")}<span className="block pl-4 text-[11px] text-slate-500">{c.detail}</span></li>
            ))}
          </ul>
        </details>
      )}
      {v?.values_applied && v.values_applied.length > 0 && (
        <div className="mt-1 text-[12px]">Applied: {v.values_applied.map((x) => `${x.name} = ${x.value}`).join(", ")}</div>
      )}
      {v?.notes && v.notes.length > 0 && <details className="mt-1"><summary className="cursor-pointer text-[12px] text-slate-500">{v.notes.length} note(s) to read — not failures</summary><ul className="list-disc pl-4 text-[12px]">{v.notes.map((n) => <li key={n}>{n}</li>)}</ul></details>}
      {m.ended?.reason && state !== "completed" && <div className="text-[12px] text-slate-500">{m.ended.reason}</div>}
    </div>
  );
}

export function AgentBubble({ m, life }: { m: AgentMessage; life: Life | null }) {
  const { mode, busy, run } = useStore(agent, (s) => ({ mode: s.mode, busy: s.busy, run: currentRun(s) }));
  const can = m.last ? run?.progress?.can : undefined;
  const qs = m.last ? questionsOf(run) : [];
  return (
    <div className="space-y-2" data-testid="agent-message">
      <ActivityBlock m={m} life={life} verbose={mode === "verbose"} />
      {m.last && qs.length > 0 && <Questions questions={qs} />}
      {m.last ? <Result m={m} /> : m.ended && m.ended.to !== "awaiting_user" && (
        <div className="text-[12px] text-slate-500" data-testid="end-line">{STATE_WORDS[m.ended.to] ?? m.ended.to}{m.ended.reason ? ` — ${m.ended.reason}` : ""}</div>
      )}
      {m.last && can && (can.continue || can.apply || can.revert) && (
        <div className="flex flex-wrap gap-1.5">
          {can.continue && <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-[12px] hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40" disabled={busy !== null} onClick={requestResume} data-testid="resume">Continue</button>}
          {can.apply && <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-[12px] hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => void applyHeld()} title="Apply what is already valid; nothing invalid is applied">Apply what holds</button>}
          {can.revert && <button className="rounded border border-slate-300 dark:border-slate-600 px-2 py-0.5 text-[12px] hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => void revert()} title="Take back everything this run applied">Revert this run</button>}
        </div>
      )}
    </div>
  );
}
