// The sheet's views, tables and notes: fit one, focus one (the others dimmed), see which unit it belongs to and whether that
// unit is parametrized.
import { useStore } from "../state/store";
import { fitView, openUnit, store } from "../state/workspace";

export function ViewsPanel() {
  const { summary, focus } = useStore(store, (s) => ({ summary: s.summary, focus: s.focusView }));
  if (!summary) return <p className="p-3 text-sm text-slate-500">No drawing open.</p>;
  const units = new Map(summary.units.map((u) => [u.id, u]));
  const kinds = ["view", "table", "notes", "title_block", "label"] as const;
  return (
    <div className="p-2 text-[13px]" data-testid="views-panel">
      {summary.notes.length > 0 && (
        <details className="mb-2 rounded bg-amber-50 dark:bg-amber-950/40 px-2 py-1 text-[12px] text-amber-900 dark:text-amber-200">
          <summary className="cursor-pointer">{summary.notes.length} note(s) from reading the file</summary>
          <ul className="list-disc pl-4">{summary.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </details>
      )}
      {kinds.map((k) => {
        const groups = summary.groups.filter((g) => g.kind === k);
        if (!groups.length) return null;
        return (
          <section key={k} className="mb-3">
            <h3 className="px-1 mb-1 text-[11px] uppercase tracking-wide text-slate-400">{k.replace("_", " ")}s</h3>
            {groups.map((g) => {
              const u = g.unit ? units.get(g.unit) : undefined;
              return (
                <div key={g.id} data-testid={`view-${g.id}`}
                  className={`group flex items-center gap-2 rounded px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${focus === g.id ? "bg-blue-50 dark:bg-amber-950/40" : ""}`}>
                  <button className="font-mono text-[12px] text-slate-500 w-9 text-left" onClick={() => fitView(g.id)} title="Fit this view">{g.id}</button>
                  <button className="flex-1 min-w-0 text-left truncate" title={g.name} onClick={() => fitView(g.id)}>
                    {g.name || <span className="text-slate-400">(no title)</span>}
                    <span className="ml-1 text-[11px] text-slate-400">{g.view_type !== "unknown" ? g.view_type : ""}{g.scale ? ` 1:${g.scale}` : ""}</span>
                  </button>
                  {u && (
                    <button className={`text-[11px] rounded px-1 ${u.parametrized ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}
                      title={`unit ${u.id}${u.parametrized ? ", parametrized" : ""}: its values`} onClick={() => { void openUnit(u.id); store.set({ leftTab: "values" }); }}>
                      {u.id}
                    </button>
                  )}
                  <button className="text-[11px] text-slate-400 opacity-0 group-hover:opacity-100" title="Dim the other views"
                    onClick={() => store.set({ focusView: focus === g.id ? null : g.id })}>{focus === g.id ? "unfocus" : "focus"}</button>
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
