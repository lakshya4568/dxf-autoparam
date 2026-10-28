// The values of a unit (and the values shared across views): pick one to see what it drives, step it up or down and the drawing follows
// at once, check the whole assembly. The camera never moves: you keep looking where you were.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { entityList } from "../api/normalize";
import type { Blocker, ComponentRow, FrozenRow, GrowthRow, MeasuredRow, ParamRow, SettleChoice, UnitInfo } from "../api/types";
import { useStore } from "../state/store";
import { checkBehaviour, chooseGrowth, clearParam, deriveIntent, fitEntities, focusParam, hideAnchorWays, hideWays, keepUnnamedAsDrawn, liveChange, openUnit, releaseKept, settleGrowth, showWays, store, takeBackChoice, unlockHeldPart } from "../state/workspace";

function fmt(v: number, unit: string): string {
  return unit === "m" ? v.toFixed(3) : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
}

/** A step that suits the size of the value: a tenth of its power of ten (600 → 10, 4.85 → 0.1, 0.5 → 0.01). Shift takes ten of them, Alt a tenth. */
function stepFor(v: number): number {
  const mag = Math.abs(v);
  return mag > 0 && isFinite(mag) ? 10 ** (Math.floor(Math.log10(mag)) - 1) : 1;
}

/** The number as typed into the field: as exact as the engine has it, without trailing noise. */
const plain = (v: number): string => String(Math.round(v * 1000) / 1000);

/** A value is a number you step: each step changes the drawing at once (one undo goes back to where you started). A typed number is taken on
 * Enter or when you leave the field, never half-typed. The original geometry is a switch in the top bar, not part of this editor. */
function ParamEditor({ row }: { row: { key: string; label: string; value: number; drawn: number; unit: string } }) {
  const param = useStore(store, (s) => s.param);
  const [text, setText] = useState(plain(row.value));
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const latest = useRef<number | null>(null); // the value a step asked for, until it is sent
  const sending = useRef(false);
  const [impact, setImpact] = useState<Record<string, unknown> | null>(null);
  const range = param?.key === row.key ? param.info?.range : undefined;
  const lo = range?.min, hi = range?.max;
  const value = Number(text);
  const valid = text.trim() !== "" && isFinite(value);
  const atDrawn = Math.abs(row.value - row.drawn) < 1e-9;
  const Chevron = ({ up }: { up: boolean }) => (
    <svg viewBox="0 0 8 5" className="h-1.5 w-2" aria-hidden="true"><path d={up ? "M1 4.2 4 1.2 7 4.2" : "M1 0.8 4 3.8 7 0.8"} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
  );

  // what the engine holds is what the field shows — except while a step of this editor is on its way
  useEffect(() => {
    if (!sending.current && latest.current === null) setText(plain(row.value));
  }, [row.value, row.unit]);

  const send = () => {
    timer.current = null;
    const v = latest.current;
    if (v === null) return;
    latest.current = null;
    sending.current = true;
    void liveChange({ [row.key]: v }).then((r) => {
      sending.current = false;
      setError(r.ok ? null : r.error ?? "refused");
      if (!r.ok) setText(plain(store.get().summary?.values[row.key] ?? row.value)); // the drawing stayed: so does the number
    });
  };
  // a step still waiting when the editor closes is not lost
  useEffect(() => () => { if (timer.current !== null) { window.clearTimeout(timer.current); send(); } }, []);
  // the range is what the engine found the drawing still holds within — information, never a fence: a value outside it is tried, and the
  // engine says what happens (accepted, with what follows; or refused, with why)
  const go = (v: number, soon = true) => {
    const v2 = Math.round(v * 1e6) / 1e6;
    setText(plain(v2));
    latest.current = v2;
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(send, soon ? 120 : 0);
  };
  const stepBy = (dir: 1 | -1, e: { shiftKey: boolean; altKey: boolean }) => {
    const base = valid ? value : row.value;
    go(base + dir * stepFor(row.drawn || row.value) * (e.shiftKey ? 10 : e.altKey ? 0.1 : 1));
  };
  const take = () => { if (valid && Math.abs(value - row.value) > 1e-9) go(value, false); else setText(plain(row.value)); };
  return (
    <div className="mt-2 rounded border border-blue-200 dark:border-amber-900 bg-blue-50/60 dark:bg-amber-950/30 p-2" data-testid="param-editor">
      <div className="flex items-center gap-2">
        <div className="flex items-stretch">
          <input className="h-8 w-24 rounded-l border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-2 num text-right focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-amber-400" inputMode="decimal" value={text}
            data-testid="param-input" aria-label={`${row.label || row.key} in ${row.unit}`} aria-invalid={!valid || undefined}
            onChange={(e) => setText(e.target.value)} onBlur={take}
            onKeyDown={(e) => {
              if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); stepBy(e.key === "ArrowUp" ? 1 : -1, e); }
              else if (e.key === "Enter") take();
              else if (e.key === "Escape") setText(plain(row.value));
            }} />
          <div className="flex w-6 flex-col divide-y divide-slate-300 dark:divide-slate-600 overflow-hidden rounded-r border border-l-0 border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800 text-slate-500">
            <button className="flex flex-1 items-center justify-center hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-40" tabIndex={-1} aria-label={`Increase ${row.label || row.key}`} title="Bigger (Shift: ×10, Alt: ÷10)"
              data-testid="param-inc" onClick={(e) => stepBy(1, e)}><Chevron up /></button>
            <button className="flex flex-1 items-center justify-center hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-40" tabIndex={-1} aria-label={`Decrease ${row.label || row.key}`} title="Smaller (Shift: ×10, Alt: ÷10)"
              data-testid="param-dec" onClick={(e) => stepBy(-1, e)}><Chevron up={false} /></button>
          </div>
        </div>
        <span className="text-slate-500">{row.unit}</span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-slate-500 num">
        <span>drawn {fmt(row.drawn, row.unit)}</span>
        {lo !== undefined && hi !== undefined && (
          <span data-testid="param-range" title={`Within this the drawing holds as it is set out now; outside it, the engine says what breaks. ${range?.min_reason ?? ""}${range?.max_reason ? ` · ${range.max_reason}` : ""}`}>
            holds {fmt(lo, row.unit)} – {fmt(hi, row.unit)}{valid && (value > hi || value < lo) ? " · outside: tried" : ""}
          </span>
        )}
      </div>
      <GrowthChooser rowKey={row.key} />
      {error && <p className="mt-1 text-[12px] text-red-600" role="alert" data-testid="param-error">Refused, the drawing stays as it was: {error}</p>}
      <div className="mt-1 flex gap-2 text-[12px]">
        <button className="underline text-blue-700 dark:text-amber-300" onClick={() => void checkBehaviour({ [row.key]: atDrawn ? row.value * 1.05 : row.value })}>Check the assembly</button>
        <button className="underline text-blue-700 dark:text-amber-300" onClick={() => void api.impact(row.key).then(setImpact)}>What would it change?</button>
        {param?.key === row.key && param.info && (
          <button className="underline text-blue-700 dark:text-amber-300" onClick={() => fitEntities(new Set([...entityList(param.info!.highlight.drives), ...entityList(param.info!.highlight.follows)]))}>Zoom to it</button>
        )}
      </div>
      {impact && <ImpactSummary data={impact} />}
    </div>
  );
}

/** How much of this unit is parametric, measured: the dimensions some named value changes, and those that stay as drawn whatever the values become. */
function DimensionDrive({ d }: { d: NonNullable<UnitInfo["dimensions"]> }) {
  const read = d.total - d.unread;
  const tip = d.constants.length ? `Stay as drawn: ${d.constants.map((c) => `${fmt(c.mm, "mm")}${c.text ? ` (${c.text})` : ""}`).join(", ")}${d.constant > d.constants.length ? ", …" : ""} mm` : "Every dimension follows a named value.";
  return (
    <p className="mb-2 px-1 text-[12px] text-slate-500" title={tip} data-testid="dimension-drive">
      Dimensions: <b className="text-slate-700 dark:text-slate-300">{d.driven}</b> of {read} change with a named value{d.constant ? <> · <span className={d.driven === 0 ? "text-amber-700 dark:text-amber-300" : ""}>{d.constant} stay as drawn</span></> : null}
    </p>
  );
}

const SIDES: Record<string, [string, string]> = { x: ["Left", "Right"], y: ["Bottom", "Top"] };
const POLICY: Record<string, "start" | "end" | "centre"> = { start_fixed: "start", end_fixed: "end", centered: "centre" };

/** One view's answer to "which side stays when this value changes": measured by the engine, with who decided it and on what evidence. Choosing a
 * side makes it the person's own plan for the whole assembly (it replaces the engine's default); the drawing does not change until the value does. */
function GrowthLine({ g, rowKey, many }: { g: GrowthRow; rowKey: string; many: boolean }) {
  const label = many ? <b className="mr-1">{g.unit}</b> : null;
  if (g.mode === "none") return <p className="text-[12px] text-slate-500" data-testid="growth-none">{label}{g.why}</p>;
  const [low, high] = SIDES[(g.from ?? g.to ?? "x")[0] === "y" ? "y" : "x"];
  const choices = [["start", `${low} stays`], ["centre", "Centred"], ["end", `${high} stays`]] as const;
  const intent = g.intent;
  // the decision is about the whole assembly (a centred box has cells whose own line stays): it is what is shown as chosen; with none, the measured side
  const active = (intent?.policy ? POLICY[intent.policy] : undefined) ?? (g.mode === "start" || g.mode === "end" || g.mode === "centre" ? g.mode : undefined);
  const engines = intent?.source === "design intent";
  const provisional = engines && intent?.status === "provisional";
  const by = !intent ? "as the set-out drew it" : engines ? (provisional ? "engine's default, provisional" : "engine's default") : "your choice";
  const evidence = (intent?.evidence ?? []).join("; ");
  return (
    <div className="mb-1" data-testid="growth-line">
      <div className="flex items-center gap-1">
        {label}
        <div className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-600 text-[12px]" role="group" aria-label={`Which side of ${rowKey} stays${many ? ` in ${g.unit}` : ""}`}>
          {choices.map(([mode, text]) => (
            <button key={mode} data-testid={`growth-${mode}`} aria-pressed={active === mode}
              className={`px-2 py-0.5 border-l first:border-l-0 border-slate-300 dark:border-slate-600 ${active === mode ? "bg-blue-600 text-white dark:bg-amber-500 dark:text-slate-950" : "bg-white dark:bg-slate-900 hover:bg-slate-100 dark:hover:bg-slate-800"}`}
              onClick={() => void chooseGrowth(rowKey, g.unit, mode)}>{text}</button>
          ))}
        </div>
      </div>
      <p className={`mt-0.5 text-[11px] ${provisional ? "text-amber-700 dark:text-amber-300" : "text-slate-500"}`} title={evidence || g.why} data-testid="growth-by">
        {by}{g.mode === "slides" || g.mode === "other" ? ` · ${g.why}` : ""}{evidence ? ` — ${evidence.length > 110 ? `${evidence.slice(0, 107)}…` : evidence}` : ""}
      </p>
      {g.undecided && <Undecided g={g} rowKey={rowKey} />}
      {!g.undecided && g.left_out && (
        <p className="mt-0.5 text-[11px] text-slate-500" title={g.left_out.why} data-testid="growth-left-out">
          Left out of its structure's growth: it keeps the direction the set-out gave it. {g.left_out.why.length > 120 ? `${g.left_out.why.slice(0, 117)}…` : g.left_out.why}
        </p>
      )}
      {(g.settled ?? []).map((c) => (
        <p key={c.choice} className="mt-0.5 text-[11px] text-slate-500" data-testid="growth-settled">
          Settled by you: {c.title}. <button className={link} data-testid="take-back" onClick={() => void takeBackChoice(g.unit, c.choice)}>Take back</button>
        </p>
      ))}
      <SettleWays rowKey={rowKey} unit={g.unit} />
      <AnchorWays rowKey={rowKey} unit={g.unit} />
    </div>
  );
}

/** What stood in the way, said by name: the site levels and held parts that would have to move, and any other line. */
function blockedWords(blocked: Blocker[]): string {
  const levels = [...new Set(blocked.filter((b) => b.kind === "level").map((b) => b.level ?? b.line))];
  const parts = [...new Set(blocked.filter((b) => b.kind === "held").map((b) => b.part ?? b.line))];
  const rest = blocked.filter((b) => b.kind !== "level" && b.kind !== "held").map((b) => b.line);
  const bits = [levels.length ? `site level${levels.length > 1 ? "s" : ""} ${levels.join(", ")}` : "", parts.length ? `held part ${parts.join(", ")}` : "", rest.length ? `line${rest.length > 1 ? "s" : ""} ${[...new Set(rest)].slice(0, 3).join(", ")}` : ""];
  return bits.filter(Boolean).join("; ");
}

/** The direction of this size could not be decided: said, with the way to ask the engine for concrete choices (each one tried for real). */
function Undecided({ g, rowKey }: { g: GrowthRow; rowKey: string }) {
  const u = g.undecided!;
  const why = u.blocked.length ? `no side can stay: pinned by ${blockedWords(u.blocked)}` : (u.evidence[0] ?? "no side can stay").replace(/^no side could stay without breaking something/, "no side can stay");
  return (
    <div className="mt-0.5" data-testid="growth-undecided">
      <p className="text-[11px] text-amber-700 dark:text-amber-300" title={u.evidence.join("; ")}>Undecided — {why.length > 150 ? `${why.slice(0, 147)}…` : `${why}.`} The set-out decides, as drawn.</p>
      <button className={`text-[12px] ${link}`} data-testid="settle-ways" onClick={() => void showWays(rowKey, g.unit)}>Ways to settle it</button>
    </div>
  );
}

function Choice({ c, rowKey, unit }: { c: SettleChoice; rowKey: string; unit: string }) {
  const discards = c.discards.length > 0;
  return (
    <li className="rounded border border-slate-200 dark:border-slate-700 p-1.5" data-testid="settle-choice" data-choice={c.id}>
      <div className="flex items-start justify-between gap-2">
        <b className="text-[12px]">{c.title}</b>
        <button className="shrink-0 rounded bg-blue-600 px-2 py-0.5 text-[12px] text-white hover:bg-blue-700 dark:bg-amber-500 dark:text-slate-950 dark:hover:bg-amber-400" data-testid="settle-choose"
          title={discards ? `Also resets the value you set for ${c.discards.join(", ")}` : "Written as your own decision; one undo takes it back"}
          onClick={() => void settleGrowth(rowKey, unit, c.id, discards)}>{discards ? "Choose, reset my value" : "Choose"}</button>
      </div>
      <p className="text-[11px] text-slate-600 dark:text-slate-300">
        {c.stays.charAt(0).toUpperCase() + c.stays.slice(1)}{c.status === "provisional" ? " (assumed: nothing else decides it)" : ""}.
        {c.moves.length > 0 && <> {c.moves.join("; ")}.</>}
      </p>
      {c.stops_being_input.length > 0 && <p className="text-[11px] text-amber-700 dark:text-amber-300">Stops being an input: {c.stops_being_input.join(", ")}.</p>}
      {c.become_inputs.length > 0 && <p className="text-[11px] text-slate-500">Becomes an input: {c.become_inputs.join(", ")}.</p>}
      {c.left_out.length > 0 && <p className="text-[11px] text-slate-500">Left out of the growth (keeps the set-out's direction): {c.left_out.map((x) => x.name).join(", ")}.</p>}
      {discards && <p className="text-[11px] text-amber-700 dark:text-amber-300">Resets the value you set for {c.discards.join(", ")}.</p>}
    </li>
  );
}

/** The concrete choices that would settle it, as the engine tried them: only what held is offered; what did not is one click away, with why. */
function SettleWays({ rowKey, unit }: { rowKey: string; unit: string }) {
  const ways = useStore(store, (s) => s.ways);
  if (!ways || ways.key !== rowKey || ways.unit !== unit) return null;
  if (ways.loading || !ways.options) return <p className="mt-1 text-[11px] text-slate-500" data-testid="settle-loading">Trying each way for real…</p>;
  const o = ways.options;
  return (
    <div className="mt-1 rounded border border-blue-200 dark:border-amber-900 bg-blue-50/50 dark:bg-amber-950/20 p-1.5" data-testid="settle">
      <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-400">
        <span>{o.choices.length ? "Ways to settle it, each tried on the sheet" : "Nothing single settles it"}</span>
        <button className={link} onClick={hideWays}>Close</button>
      </div>
      {o.choices.length > 0 && <ul className="space-y-1">{o.choices.map((c) => <Choice key={c.id} c={c} rowKey={rowKey} unit={unit} />)}</ul>}
      {o.notes.map((n) => <p key={n} className="mt-1 text-[11px] text-slate-500">{n}</p>)}
      {o.rejected.length > 0 && (
        <details className="mt-1 text-[11px] text-slate-500" data-testid="settle-rejected">
          <summary className="cursor-pointer">Tried and did not hold ({o.rejected.length})</summary>
          <ul className="ml-3 list-disc">{o.rejected.map((r) => <li key={r.id}>{r.why}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

const SIDE_SAID: Record<string, string> = { start: "its start side stays", centre: "centred", end: "its far side stays" };

/** A side the sheet refused, as a question: what stood in the way, by part, and the ways out the engine tried on the whole sheet — only what holds
 * can be chosen; what did not hold is one click away, with why. A choice is written as the person's own (one undo takes it back). */
function AnchorWays({ rowKey, unit }: { rowKey: string; unit: string }) {
  const w = useStore(store, (s) => s.anchorWays);
  if (!w || w.key !== rowKey || w.unit !== unit) return null;
  if (w.loading || !w.options) return <p className="mt-1 text-[11px] text-slate-500" data-testid="anchor-ways-loading">Refused — trying the ways out on the whole sheet…</p>;
  const o = w.options;
  const refused = o.refused.replace(/^refused, nothing changed: /, "");
  return (
    <div className="mt-1 rounded border border-amber-300 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/20 p-1.5" data-testid="anchor-ways">
      <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-400">
        <span>{SIDE_SAID[w.mode] ?? w.mode} was refused — what should happen?</span>
        <button className={link} onClick={hideAnchorWays}>Close</button>
      </div>
      {o.blocked.length > 0 && (
        <div className="mb-1 text-[11px] text-slate-600 dark:text-slate-300" data-testid="anchor-blocked">
          In the way:
          <ul className="ml-3 list-disc">
            {o.blocked.map((b) => (
              <li key={b.part ?? "none"}>
                <b>{b.part ?? "no part"}</b>{b.existing ? " (existing work)" : b.existing === false ? " (new work)" : ""}: {b.count} entit{b.count === 1 ? "y" : "ies"} —{" "}
                <button className={link} onClick={() => fitEntities(new Set(b.sheet))}>{b.entities.slice(0, 6).join(", ")}{b.count > 6 ? "…" : ""}</button>
                {b.layers.length > 0 && <span className="text-slate-500"> · {b.layers.join(", ")}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {o.choices.length > 0 ? (
        <ul className="space-y-1">
          {o.choices.map((c) => (
            <li key={c.id} className="flex items-start justify-between gap-2 rounded border border-slate-200 dark:border-slate-700 p-1.5" data-testid="anchor-choice">
              <span className="text-[12px]">{c.title}</span>
              <button className="shrink-0 rounded bg-blue-600 px-2 py-0.5 text-[12px] text-white hover:bg-blue-700 dark:bg-amber-500 dark:text-slate-950"
                data-testid="anchor-choose" onClick={() => void chooseGrowth(rowKey, unit, c.mode, { decisions: c.decisions, keep_as_drawn: c.keep_as_drawn })}>Choose</button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[11px] text-amber-700 dark:text-amber-300" data-testid="anchor-none">
          No way out holds on the whole sheet: the drawing itself has to say what the things in the way do when this value changes (extended, cut back,
          moved, or not structure at all). {refused.length > 220 ? `${refused.slice(0, 217)}…` : refused}
        </p>
      )}
      {o.notes.map((n) => <p key={n} className="mt-1 text-[11px] text-slate-500">{n}</p>)}
      {o.rejected.length > 0 && (
        <details className="mt-1 text-[11px] text-slate-500" data-testid="anchor-rejected">
          <summary className="cursor-pointer">Tried and did not hold ({o.rejected.length})</summary>
          <ul className="ml-3 list-disc">{o.rejected.map((r) => <li key={r.id}><b>{r.title}</b>: {r.why}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function GrowthChooser({ rowKey }: { rowKey: string }) {
  const param = useStore(store, (s) => s.param);
  const rows = param?.key === rowKey ? param.info?.growth : undefined;
  if (!rows || rows.length === 0) return null;
  return (
    <div className="mt-2 border-t border-blue-200/70 dark:border-amber-900/70 pt-1.5" data-testid="growth">
      <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-400">When it changes</div>
      {rows.map((g) => <GrowthLine key={g.unit} g={g} rowKey={rowKey} many={rows.length > 1} />)}
    </div>
  );
}

function ImpactSummary({ data }: { data: Record<string, unknown> }) {
  const comps = (data.components ?? {}) as Record<string, string[]>;
  const ann = (data.annotations ?? {}) as { updating?: { text: string; reads: string }[]; problems?: unknown[] };
  const q = (data.questions ?? []) as string[];
  return (
    <div className="mt-2 text-[12px] text-slate-700 dark:text-slate-300" data-testid="impact">
      {Object.entries(comps).map(([k, v]) => <div key={k}><b>{k}</b>: {v.slice(0, 8).join(", ")}{v.length > 8 ? ` +${v.length - 8}` : ""}</div>)}
      {ann.updating && ann.updating.length > 0 && <div>dimensions that update: {ann.updating.slice(0, 6).map((a) => a.reads).join("; ")}</div>}
      {Array.isArray(data.invariants_kept) && <div className="text-slate-500">kept: {(data.invariants_kept as string[]).slice(0, 10).join(", ")}</div>}
      {q.map((x) => <div key={x} className="text-amber-700 dark:text-amber-300">? {x}</div>)}
    </div>
  );
}

const link = "underline text-blue-700 dark:text-amber-300";

/** One group of values: a heading with its count; `fold` makes it a collapsed list (nothing is hidden for good, it is one click away). */
function Group({ title, count, children, fold, open, testid, action }: { title: string; count: number; children: React.ReactNode; fold?: boolean; open?: boolean; testid?: string; action?: React.ReactNode }) {
  const head = (
    <>
      <span>{title}</span>
      <span className="ml-1 normal-case tracking-normal text-slate-400">{count}</span>
    </>
  );
  const cls = "px-1 mb-1 text-[11px] uppercase tracking-wide text-slate-400";
  return fold ? (
    <details className="mb-3" open={open} data-testid={testid}>
      <summary className={`${cls} cursor-pointer select-none`}>{head}</summary>
      {action && <div className="px-1 pb-1 text-[12px]">{action}</div>}
      {children}
    </details>
  ) : (
    <section className="mb-3" data-testid={testid}>
      <h3 className={cls}>{head}</h3>
      {children}
    </section>
  );
}

/** The unit's parts as a tree: a click selects the part's own geometry on the drawing (the camera stays), a mark where the drawing's own label on
 * the part says something else than its name. */
function PartRows({ parts }: { parts: ComponentRow[] }) {
  const sel = useStore(store, (x) => x.selection);
  const depth = (c: ComponentRow): number => {
    let d = 0;
    let at = c.parent;
    const seen = new Set<string>();
    while (at && !seen.has(at) && d < 6) {
      seen.add(at);
      d += 1;
      at = parts.find((q) => q.name === at)?.parent ?? null;
    }
    return d;
  };
  return (
    <>
      {parts.map((c) => {
        const ents = c.entities ?? [];
        const on = ents.length > 0 && ents.every((i) => sel.has(i));
        return (
          <button key={c.name} data-testid={`part-${c.name}`} disabled={!ents.length}
            className={`w-full flex items-center gap-2 rounded px-1.5 py-0.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-60 ${on ? "bg-blue-50 dark:bg-amber-950/40" : ""}`}
            style={{ paddingLeft: `${6 + 12 * depth(c)}px` }}
            title={[c.label_doubt, c.drawing_says?.length ? `The drawing labels it: ${c.drawing_says.join("; ")}` : "", c.label_checked ? `Kept: ${c.label_checked}` : ""].filter(Boolean).join("\n")}
            onClick={() => store.set({ selection: on ? new Set() : new Set(ents) })}>
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium">{c.name}</span>
              <span className="ml-1 text-[11px] text-slate-400">{c.type}{c.existing ? " · existing" : ""}</span>
            </span>
            {c.label_doubt && <span className="shrink-0 text-[11px] text-amber-600 dark:text-amber-300" data-testid={`part-doubt-${c.name}`}>⚠ labelled {c.drawing_says?.[0]?.slice(0, 24)}</span>}
            <span className="num shrink-0 text-[11px] text-slate-400">{ents.length}</span>
          </button>
        );
      })}
    </>
  );
}

function ParamRows({ rows, param, pick }: { rows: ParamRow[]; param: { key: string } | null; pick: (key: string) => void }) {
  return (
    <>
      {rows.map((p) => (
        <div key={p.key}>
          <button data-testid={`param-${p.name}`} className={`w-full flex items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${param?.key === p.key ? "bg-blue-50 dark:bg-amber-950/40" : ""}`} onClick={() => pick(p.key)}>
            <span className="min-w-0 flex-1">
              <span className={`block truncate ${p.generic ? "text-slate-500" : "font-medium"}`}>{p.name}{p.shared && <span className="ml-1 text-[10px] text-blue-600 dark:text-amber-300">shared</span>}</span>
              {p.label && p.label !== p.name && <span className="block truncate text-[11px] text-slate-400">{p.label}</span>}
            </span>
            <span className={`num ${p.changed ? "text-orange-600" : "text-slate-600 dark:text-slate-300"}`}>{fmt(p.value, p.unit)}</span>
            <span className="text-[11px] text-slate-400 w-6">{p.unit}</span>
          </button>
          {param?.key === p.key && <ParamEditor row={p} />}
        </div>
      ))}
    </>
  );
}

/** Named quantities that are read from the drawing, not set: a size of work that is kept as drawn says so and offers to unlock the part. */
function MeasuredRows({ rows, uid }: { rows: MeasuredRow[]; uid: string }) {
  return (
    <>
      {rows.map((m) => (
        <div key={m.name} data-testid={`measured-${m.name}`} className="flex items-center gap-2 rounded px-1.5 py-1">
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{m.name}</span>
            <span className="block truncate text-[11px] text-slate-400" title={m.between ? `measured between ${m.between.join(" and ")}` : m.expr}>
              {m.held ? `${m.part} is kept as drawn: a reading, not an input` : m.part ? `in ${m.part}` : "worked out by the set-out"}
            </span>
          </span>
          <span className="num text-slate-600 dark:text-slate-300">{fmt(m.value, m.unit)}</span>
          <span className="text-[11px] text-slate-400 w-6">{m.unit}</span>
          {m.held && m.part && (
            <button className={`text-[11px] ${link}`} data-testid={`unlock-${m.name}`} title={`Stop keeping ${m.part} as drawn: ${m.name} becomes an input you can change. Nothing moves until you change it.`}
              onClick={() => void unlockHeldPart(uid, m.part as string)}>Unlock</button>
          )}
        </div>
      ))}
    </>
  );
}

function KeptRows({ rows, uid }: { rows: FrozenRow[]; uid: string }) {
  return (
    <>
      {rows.map((f) => (
        <div key={f.name} className="flex items-center gap-2 px-1.5 py-0.5 text-slate-500" title={`${f.label}${f.measures ? ` · between ${f.measures.join(" and ")}` : ""} — ${f.why}`}>
          <span className="min-w-0 flex-1 truncate">{f.name}</span>
          <span className="num">{fmt(f.value, f.unit)}</span>
          <span className="text-[11px] text-slate-400 w-6">{f.unit}</span>
          <button className={`text-[11px] ${link}`} onClick={() => void releaseKept(uid, [f.name])}>Release</button>
        </div>
      ))}
    </>
  );
}

export function ValuesPanel() {
  const { summary, unit, param, focus } = useStore(store, (s) => ({ summary: s.summary, unit: s.unit, param: s.param, focus: s.focusView }));
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (!summary || unit) return;
    const g = focus ? summary.groups.find((x) => x.id === focus) : undefined;
    const uid = g?.unit ?? summary.units.find((u) => u.parametrized)?.id ?? summary.units[0]?.id;
    if (uid) void openUnit(uid);
  }, [summary, unit, focus]);
  // The list is the engine's, as of the revision it was read at. When the sheet moves on (an apply, an undo, the agent's commit, a reopened
  // session) the open unit is read again: a value the agent just named is there without a click.
  useEffect(() => {
    if (summary && unit && unit.revision !== undefined && unit.revision !== summary.revision) void openUnit(unit.id);
  }, [summary?.revision, unit?.revision]);
  const match = (text: string) => !filter || text.toLowerCase().includes(filter.toLowerCase());
  const groups = useMemo(() => {
    const rows = unit?.params ?? [];
    return {
      named: rows.filter((p) => !p.generic && !p.shared && match(`${p.name} ${p.label}`)),
      loose: rows.filter((p) => p.generic && match(`${p.name} ${p.label}`)),
      shared: rows.filter((p) => p.shared).length,
      measured: (unit?.measured ?? []).filter((m) => match(`${m.name} ${m.label}`)),
      kept: (unit?.frozen ?? []).filter((f) => match(`${f.name} ${f.label}`)),
    };
  }, [unit, filter]);
  if (!summary) return <p className="p-3 text-sm text-slate-500">No drawing open.</p>;
  const pick = (key: string) => { if (param?.key === key) clearParam(); else void focusParam(key); };
  const here = summary.units.find((u) => u.id === unit?.id);
  const anyParametrized = summary.units.some((u) => u.parametrized);
  return (
    <div className="p-2 text-[13px]" data-testid="values-panel">
      <div className="flex items-center gap-2 mb-2">
        <select className="rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1 py-0.5" value={unit?.id ?? ""} onChange={(e) => void openUnit(e.target.value)} data-testid="unit-select">
          {summary.units.map((u) => <option key={u.id} value={u.id}>{u.id} · {u.views.join(" + ")}{u.parametrized ? " ✓" : ""}</option>)}
        </select>
        <input className="flex-1 rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1.5 py-0.5" placeholder="filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {unit?.dimensions && unit.dimensions.total > 0 && <DimensionDrive d={unit.dimensions} />}
      {summary.shared.length > 0 && (
        <Group title="Shared across views" count={summary.shared.length} testid="shared-group">
          {summary.shared.map((p) => (
            <div key={p.id}>
              <button data-testid={`shared-${p.name}`} className={`w-full flex justify-between rounded px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${param?.key === p.name ? "bg-blue-50 dark:bg-amber-950/40" : ""}`} onClick={() => pick(p.name)}>
                <span className="font-medium">{p.name}</span><span className="num text-slate-500">{fmt(summary.values[p.name] ?? p.value, p.unit)} {p.unit}</span>
              </button>
              {param?.key === p.name && <ParamEditor row={{ key: p.name, label: p.label, value: summary.values[p.name] ?? p.value, drawn: p.value, unit: p.unit }} />}
            </div>
          ))}
        </Group>
      )}
      {unit && unit.components.length > 0 && (
        <Group title={`${unit.id} — parts`} count={unit.components.length} fold open={unit.components.some((c) => c.label_doubt)} testid="parts-group">
          <PartRows parts={unit.components} />
        </Group>
      )}
      <Group title={unit ? `${unit.id} — named values` : "named values"} count={groups.named.length} testid="named-group">
        <ParamRows rows={groups.named} param={param} pick={pick} />
        {unit && groups.named.length === 0 && !filter && (
          <p className="px-1.5 text-[12px] text-slate-500">
            {here?.parametrized ? "Every value of this unit that somebody named is shared across views (listed above)." : "Nobody has named this unit's values yet: the sizes below are what the analysis measured."}
          </p>
        )}
      </Group>
      {unit && groups.measured.length > 0 && (
        <Group title="Measured, not inputs" count={groups.measured.length} testid="measured-group">
          <MeasuredRows rows={groups.measured} uid={unit.id} />
        </Group>
      )}
      {groups.loose.length > 0 && (
        <Group title="Measured sizes nobody named" count={groups.loose.length} fold open={groups.named.length === 0} testid="generic-group"
          action={here?.parametrized && unit && (
            <button className={link} data-testid="keep-as-drawn" title="They stop being inputs and keep the numbers they have: the drawing does not change. One undo brings them back; Release gives any of them back."
              onClick={() => void keepUnnamedAsDrawn(unit.id)}>Keep these as drawn</button>
          )}>
          <ParamRows rows={groups.loose} param={param} pick={pick} />
        </Group>
      )}
      {unit && groups.kept.length > 0 && (
        <Group title="Kept as drawn" count={groups.kept.length} fold testid="kept-group"
          action={<button className={link} data-testid="release-all" onClick={() => void releaseKept(unit.id)}>Release all</button>}>
          <KeptRows rows={groups.kept} uid={unit.id} />
        </Group>
      )}
      {unit && (unit.settled ?? []).length > 0 && (
        <Group title="Your choices" count={unit.settled!.length} fold testid="settled-group">
          {unit.settled!.map((c) => (
            <div key={c.choice} className="flex items-center gap-2 px-1.5 py-0.5 text-slate-500">
              <span className="min-w-0 flex-1 truncate" title={c.title}>{c.title}</span>
              <button className={`text-[11px] ${link}`} data-testid={`take-back-${c.choice}`} onClick={() => void takeBackChoice(unit.id, c.choice)}>Take back</button>
            </div>
          ))}
        </Group>
      )}
      {anyParametrized && !filter && (
        <p className="mt-2 px-1 text-[12px] text-slate-500">
          <button className={link} data-testid="derive-intent" title="Which side of each value stays when it changes, decided again from the drawing (symmetry, what is fixed, existing work). What you chose stays; one undo takes it back."
            onClick={() => void deriveIntent(unit?.id)}>Work out growth directions again</button>
          {" · "}
          <button className={link} data-testid="derive-intent-all" onClick={() => void deriveIntent()}>every unit</button>
        </p>
      )}
      {anyParametrized && !filter && (
        <p className="mt-2 px-1 text-[12px] text-slate-500">
          <button className={link} data-testid="keep-all-as-drawn" title="Every unit the agent parametrized: the measured sizes nobody named are kept as drawn; the drawing does not change." onClick={() => void keepUnnamedAsDrawn()}>
            Keep every unit's unnamed sizes as drawn
          </button>
        </p>
      )}
    </div>
  );
}
