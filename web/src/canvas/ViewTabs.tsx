// One tab per view the engine found on the sheet, beside "Sheet": a tab opens the view as its own workspace — its own entities only, the camera on
// it, and every coordinate the page says in the view's own frame (real mm from its own origin, RL where it states a level). The sheet itself does not
// change: a tab is a way of looking at it, and edits made there are the sheet's.
import type { Group } from "../api/types";
import { useStore } from "../state/store";
import { openView, store } from "../state/workspace";

const NONE: Group[] = []; // one empty list: a new [] on every read would never equal the last one, and the store would read it for ever

export function ViewTabs() {
  const s = useStore(store, (x) => ({ groups: x.summary?.groups ?? NONE, tab: x.viewTab }));
  const views = s.groups.filter((g) => g.kind === "view");
  if (!views.length) return null;
  const cls = (on: boolean) =>
    `shrink-0 whitespace-nowrap rounded-t px-2.5 py-1 text-[12px] border-b-2 ${on
      ? "border-blue-600 text-blue-700 dark:border-amber-400 dark:text-amber-300 bg-white dark:bg-[#0f141a]"
      : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"}`;
  return (
    <nav className="flex items-end gap-0.5 overflow-x-auto border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#11161d] px-2 shrink-0"
      aria-label="Views" data-testid="view-tabs">
      <button className={cls(s.tab === null)} onClick={() => openView(null)} data-testid="view-tab-sheet" aria-pressed={s.tab === null}>Sheet</button>
      {views.map((g) => (
        <button key={g.id} className={cls(s.tab === g.id)} onClick={() => openView(g.id)} data-testid={`view-tab-${g.id}`} aria-pressed={s.tab === g.id}
          title={[g.name, g.local ? `x from ${g.local.x_from}; y from ${g.local.y_from}` : ""].filter(Boolean).join("\n")}>
          <span className="text-slate-400 mr-1">{g.id}</span>{(g.name || "(no title)").slice(0, 28)}{g.scale ? <span className="ml-1 text-slate-400">1:{g.scale}</span> : null}
        </button>
      ))}
    </nav>
  );
}
