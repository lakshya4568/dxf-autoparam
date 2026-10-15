// A small external store (no framework): components subscribe with a selector and re-render only when what they read changes
// (compared shallowly, so a selector may return a fresh object of the same values).
import { useCallback, useRef, useSyncExternalStore } from "react";

export class Store<T extends object> {
  private state: T;
  private listeners = new Set<() => void>();

  constructor(init: T) {
    this.state = init;
  }

  get(): T {
    return this.state;
  }

  set(patch: Partial<T> | ((s: T) => Partial<T>)): void {
    const next = typeof patch === "function" ? patch(this.state) : patch;
    this.state = { ...this.state, ...next };
    for (const l of this.listeners) l();
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
}

export function shallowEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) return false;
  const ka = Object.keys(a as object), kb = Object.keys(b as object);
  if (ka.length !== kb.length) return false;
  for (const k of ka) if (!Object.is((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k])) return false;
  return true;
}

export function useStore<T extends object, U>(store: Store<T>, selector: (s: T) => U): U {
  const last = useRef<{ value: U } | null>(null);
  const get = useCallback(() => {
    const v = selector(store.get());
    if (last.current && shallowEqual(last.current.value, v)) return last.current.value;
    last.current = { value: v };
    return v;
  }, [store, selector]);
  return useSyncExternalStore(store.subscribe, get, get);
}
