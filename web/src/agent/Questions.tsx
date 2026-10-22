// The agent needs a decision: multiple-choice questions, each with the options the agent (or the engine) sees, what each means, the one it
// would pick marked, a checkbox list where several may apply, and a way to answer in the person's own words. Nothing is applied until the
// person answers; the answer goes back to the same run.
import { useState } from "react";
import { useStore } from "../state/store";
import { agent, requestAnswer } from "../state/agent";
import type { RunQuestion } from "../api/types";

const JOIN = " | "; // the engine's separator for an answer that picks several options

export function Questions({ questions }: { questions: RunQuestion[] }) {
  const busy = useStore(agent, (s) => s.busy);
  const [picked, setPicked] = useState<Record<string, string[]>>(() => Object.fromEntries(questions.map((q) => [q.id, q.recommended ? [q.recommended] : []])));
  const [words, setWords] = useState<Record<string, string>>({});
  const own = (q: RunQuestion) => (words[q.id] ?? "").trim();
  // one choice, or the person's own words in its place; several choices, with their own words as one more
  const answerOf = (q: RunQuestion): string => {
    const chosen = picked[q.id] ?? [];
    return q.multi ? [...chosen, ...(own(q) ? [own(q)] : [])].join(JOIN) : own(q) || chosen[0] || "";
  };
  const ready = questions.every((q) => answerOf(q) !== "");
  const choose = (q: RunQuestion, o: string) =>
    setPicked((p) => {
      const now = p[q.id] ?? [];
      return { ...p, [q.id]: q.multi ? (now.includes(o) ? now.filter((x) => x !== o) : [...now, o]) : [o] };
    });
  const submit = () => {
    const answers: Record<string, string> = {};
    const notes: string[] = [];
    for (const q of questions) {
      if (own(q)) notes.push(`${q.text.slice(0, 60)}: ${own(q)}`);
      answers[q.id] = answerOf(q);
    }
    requestAnswer(answers, notes.join("\n"));
  };
  return (
    <div className="rounded-md border border-amber-300 dark:border-amber-700/70 bg-amber-50/60 dark:bg-amber-950/20 p-2.5" data-testid="questions">
      <div className="text-[13px] font-medium">Your decision is needed</div>
      <div className="text-[11px] text-slate-500">Nothing is applied until you answer. The agent continues with exactly what you choose.</div>
      {questions.map((q) => {
        const chosen = picked[q.id] ?? [];
        return (
          <fieldset key={q.id} className="mt-2" data-testid="question" data-multi={!!q.multi}>
            {q.header && <span className="mr-1.5 rounded bg-amber-200/70 dark:bg-amber-900/50 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-amber-900 dark:text-amber-200" data-testid="question-header">{q.header}</span>}
            <legend className="inline text-[12px]">{q.about === "anchor" ? "Which side stays when this value changes?" : q.text}</legend>
            {q.why && <div className="text-[11px] text-slate-500">{q.why}</div>}
            {q.multi && <div className="text-[11px] text-slate-500">Choose any that apply.</div>}
            {(q.options ?? []).map((o) => {
              const on = chosen.includes(o) && (q.multi || !own(q));
              return (
                <label key={o} className={`mt-0.5 flex items-start gap-2 rounded px-1.5 py-0.5 text-[12px] ${on ? "bg-amber-100/70 dark:bg-amber-900/30" : ""}`} data-testid="option">
                  <input className="mt-0.5" type={q.multi ? "checkbox" : "radio"} name={`q-${q.id}`} checked={chosen.includes(o)} onChange={() => choose(q, o)} />
                  <span>
                    {o}{q.recommended === o && <span className="ml-1 text-slate-400">(recommended)</span>}
                    {q.descriptions?.[o] && <span className="block text-[11px] text-slate-500">{q.descriptions[o]}</span>}
                  </span>
                </label>
              );
            })}
            <input className="mt-1 w-full rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1.5 py-0.5 text-[12px]" placeholder={(q.options ?? []).length ? "or say it in your own words…" : "your answer…"}
              value={words[q.id] ?? ""} onChange={(e) => setWords({ ...words, [q.id]: e.target.value })} aria-label="in your own words" />
          </fieldset>
        );
      })}
      <button className="mt-2 rounded bg-blue-600 px-2.5 py-1 text-[12px] text-white dark:bg-amber-500 dark:text-slate-950 disabled:opacity-40" disabled={!ready || busy !== null} onClick={submit} data-testid="answer-send">Continue with my answers</button>
    </div>
  );
}
