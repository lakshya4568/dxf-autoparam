// One tool call as the person sees it: the tool's name and whether it ran — nothing it was given and nothing it returned.
// (A refusal is the agent's to repair and the verdict's to report; the person reads what happened in the progress lines and the result.)
import type { ToolCall } from "./model";
import { STATE_LABEL, ToolMark } from "./StatusMark";

export function ToolRow({ call }: { call: ToolCall }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11.5px] text-slate-500 dark:text-slate-400" data-testid="tool-row" data-state={call.state} data-tool={call.name} title={STATE_LABEL[call.state]}>
      <ToolMark state={call.state} />
      <code className={call.state === "failed" ? "text-red-700 dark:text-red-300" : ""}>{call.name}</code>
    </span>
  );
}
