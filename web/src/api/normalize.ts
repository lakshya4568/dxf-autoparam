// The engine's groups of entities are read defensively: one arrived as an object ({} when empty, label → entities when not) where the page
// iterated a list, and the click on a value silently did nothing. Whatever shape a group has, the page gets numbers; nothing here throws.

/** Entity indices from any shape a group arrives in: a list of numbers, a list of {set: [...]}, a list of lists, or an object of label → any
 * of those. null, undefined and anything unreadable are an empty group. */
export function entityList(v: unknown, depth = 0): number[] {
  if (depth > 4 || v === null || v === undefined) return [];
  if (typeof v === "number") return Number.isInteger(v) ? [v] : [];
  if (Array.isArray(v)) return v.flatMap((x) => entityList(x, depth + 1));
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (Array.isArray(o.set)) return entityList(o.set, depth + 1);
    return Object.values(o).flatMap((x) => entityList(x, depth + 1));
  }
  return [];
}

export function entitySet(v: unknown): Set<number> {
  return new Set(entityList(v));
}
