// The agent needs a decision: each question with the engine's options (its suggestion marked) and a free-text way out. Nothing is applied
// until the person answers; the answer goes back to the same run.
import { useState } from "react";
import { useStore } from "../state/store";
import { agent, requestAnswer } from "../state/agent";
import type { RunQuestion } from "../api/types";

export function Questions({ questions }: { questions: RunQuestion[] }) {
  const busy = useStore(agent, (s) => s.busy);
  const [picked, setPicked] = useState<Record<string, string>>(() => Object.fromEntries(questions.map((q) => [q.id, q.recommended ?? ""])));
  const [words, setWords] = useState<Record<string, string>>({});
  const ready = questions.every((q) => (words[q.id] ?? "").trim() || picked[q.id]);
  const submit = () => {
    const answers: Record<string, string> = {};
    const notes: string[] = [];
    for (const q of questions) {
      const w = (words[q.id] ?? "").trim();
      if (w) notes.push(`${q.text.slice(0, 60)}: ${w}`);
      answers[q.id] = w || picked[q.id];
    }
    requestAnswer(answers, notes.join("\n"));
  };
  return (
    <div className="rounded-md border border-amber-300 dark:border-amber-700/70 bg-amber-50/60 dark:bg-amber-950/20 p-2.5" data-testid="questions">
      <div className="text-[13px] font-medium">Your decision is needed</div>
      <div className="text-[11px] text-slate-500">Nothing is applied until you answer. The agent continues with exactly what you choose.</div>
      {questions.map((q) => (
        <fieldset key={q.id} className="mt-2" data-testid="question">
          <legend className="text-[12px]">{q.about === "anchor" ? "Which side stays when this value changes?" : q.text}</legend>
          {q.why && <div className="text-[11px] text-slate-500">{q.why}</div>}
          {(q.options ?? []).map((o) => (
            <label key={o} className={`mt-0.5 flex items-center gap-2 rounded px-1.5 py-0.5 text-[12px] ${picked[q.id] === o && !(words[q.id] ?? "").trim() ? "bg-amber-100/70 dark:bg-amber-900/30" : ""}`}>
              <input type="radio" name={`q-${q.id}`} checked={picked[q.id] === o} onChange={() => setPicked({ ...picked, [q.id]: o })} />
              {o}{q.recommended === o && <span className="text-slate-400">(suggested)</span>}
            </label>
          ))}
          <input className="mt-1 w-full rounded border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 px-1.5 py-0.5 text-[12px]" placeholder={(q.options ?? []).length ? "or say it in your own words…" : "your answer…"}
            value={words[q.id] ?? ""} onChange={(e) => setWords({ ...words, [q.id]: e.target.value })} />
        </fieldset>
      ))}
      <button className="mt-2 rounded bg-blue-600 px-2.5 py-1 text-[12px] text-white disabled:opacity-40" disabled={!ready || busy !== null} onClick={submit} data-testid="answer-send">Continue with my answers</button>
    </div>
  );
}
