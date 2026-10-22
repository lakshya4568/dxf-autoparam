// The drawing canvas: draws the engine's primitives with the renderer, and turns the person's gestures into camera moves and
// selections. Wheel zooms about the cursor; drag (or middle / right drag, or space + drag) pans; a click picks the nearest
// entity (shift adds); F fits the sheet, V the selected view, Z the selection, Backspace goes back to the previous view.
import { useEffect, useRef, useState } from "react";
import { sayLocal } from "./frames";
import { pick } from "./hit";
import { render, visibleFilter } from "./renderer";
import { DARK, LIGHT } from "./styles";
import { keepOnScreen, panBy, toWorld, zoomAt } from "./viewport";
import { useStore } from "../state/store";
import { back, fitSelection, fitSheet, fitView, select, setCamera, setHover, store } from "../state/workspace";

export function CanvasView() {
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const raf = useRef(0);
  const drag = useRef<{ x: number; y: number; moved: boolean; button: number } | null>(null);
  const space = useRef(false);
  const theme = useStore(store, (s) => s.theme);
  const tab = useStore(store, (s) => (s.viewTab ? s.summary?.groups.find((g) => g.id === s.viewTab) ?? null : null));
  const [cursor, setCursor] = useState<[number, number] | null>(null); // the pointer on the drawing, sheet units

  // redraw on any state change (one frame per animation frame)
  useEffect(() => {
    const draw = () => {
      raf.current = 0;
      const c = ref.current;
      if (!c) return;
      const s = store.get();
      const ctx = c.getContext("2d");
      if (!ctx || !s.index) {
        if (ctx) {
          ctx.fillStyle = (s.theme === "dark" ? DARK : LIGHT).bg;
          ctx.fillRect(0, 0, c.width, c.height);
        }
        return;
      }
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const stats = render(ctx, {
        prims: s.prims, styles: s.styles, index: s.index, cam: s.cam, W: s.W, H: s.H, theme: s.theme === "dark" ? DARK : LIGHT,
        hiddenLayers: s.hiddenLayers, hiddenStatus: s.hiddenStatus, statusOf: s.statusOf, overlays: s.overlays, selection: s.selection,
        hover: s.hover, highlight: s.highlight, preview: s.preview ? { ents: s.preview.ents, prims: s.preview.prims } : null, original: s.original?.prims ?? null, issues: s.issues,
        focusView: s.focusView, isolate: s.viewTab !== null,
      });
      (window as unknown as { __frame?: unknown }).__frame = stats;
    };
    const schedule = () => {
      if (!raf.current) raf.current = requestAnimationFrame(draw);
    };
    const unsub = store.subscribe(schedule);
    schedule();
    return () => {
      unsub();
      cancelAnimationFrame(raf.current);
    };
  }, []);

  // size the canvas to its box. A panel opening or closing (the inspector on a selection, the agent) resizes it: the drawing stays where it is
  // ON THE SCREEN — what the person was looking at does not slide away, and nothing is refit. (The camera keeps the world point at the canvas
  // centre; with the centre itself moving across the window, the content used to jump by half of every panel's width.)
  useEffect(() => {
    const el = wrap.current, c = ref.current;
    if (!el || !c) return;
    let last: { left: number; top: number; W: number; H: number } | null = null;
    const ro = new ResizeObserver(() => {
      const dpr = window.devicePixelRatio || 1;
      const W = Math.max(50, el.clientWidth), H = Math.max(50, el.clientHeight);
      const r = el.getBoundingClientRect();
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
      c.style.width = `${W}px`;
      c.style.height = `${H}px`;
      const s = store.get();
      if (last && s.fitted) {
        const shift = keepOnScreen(s.cam, last, { left: r.left, top: r.top, W, H });
        store.set({ W, H, cam: shift });
      } else {
        store.set({ W, H });
      }
      last = { left: r.left, top: r.top, W, H };
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // keyboard
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.key === " ") space.current = true;
      if (e.key === "f" || e.key === "F") fitSheet();
      else if (e.key === "v" || e.key === "V") {
        const s = store.get();
        const first = [...s.selection][0];
        const gid = s.focusView ?? (first !== undefined ? s.prims.find((p) => p.i === first)?.v : undefined);
        if (gid) fitView(gid);
      } else if (e.key === "z" && !e.metaKey && !e.ctrlKey) fitSelection();
      else if (e.key === "Backspace") back();
      else if (e.key === "Escape") void select(null);
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === " ") space.current = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  const local = (e: { clientX: number; clientY: number }) => {
    const r = ref.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };

  const pickAt = (sx: number, sy: number): number | null => {
    const s = store.get();
    if (!s.index) return null;
    const [x, y] = toWorld(s.cam, s.W, s.H, sx, sy);
    const tol = 6 / s.cam.s;
    const ids = s.index.query([x - tol, y - tol, x + tol, y + tol]);
    const ok = visibleFilter({
      prims: s.prims, styles: s.styles, index: s.index, cam: s.cam, W: s.W, H: s.H, theme: LIGHT, hiddenLayers: s.hiddenLayers,
      hiddenStatus: s.hiddenStatus, statusOf: s.statusOf, overlays: s.overlays, selection: s.selection, hover: null, highlight: null,
      preview: null, issues: s.issues, focusView: s.focusView, isolate: s.viewTab !== null,
    });
    const n = pick(s.prims, ids, x, y, tol, ok);
    return n === null ? null : s.prims[n].i;
  };

  return (
    <div ref={wrap} className="relative h-full w-full overflow-hidden" data-testid="canvas-wrap">
      <canvas
        ref={ref}
        data-testid="canvas"
        className={`block select-none ${theme === "dark" ? "bg-[#0f141a]" : "bg-white"}`}
        onContextMenu={(e) => e.preventDefault()}
        onWheel={(e) => {
          const [sx, sy] = local(e);
          const s = store.get();
          setCamera(zoomAt(s.cam, s.W, s.H, sx, sy, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018))));
        }}
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, moved: false, button: e.button };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) {
            const dx = e.clientX - d.x, dy = e.clientY - d.y;
            if (d.moved || Math.abs(dx) + Math.abs(dy) > 3) {
              d.moved = true;
              setCamera(panBy(store.get().cam, dx, dy));
              d.x = e.clientX;
              d.y = e.clientY;
            }
            return;
          }
          const [sx, sy] = local(e);
          setHover(pickAt(sx, sy));
          const st = store.get();
          setCursor(toWorld(st.cam, st.W, st.H, sx, sy) as [number, number]);
        }}
        onPointerUp={(e) => {
          const d = drag.current;
          drag.current = null;
          if (d && !d.moved && d.button === 0 && !space.current) {
            const [sx, sy] = local(e);
            void select(pickAt(sx, sy), e.shiftKey);
          }
        }}
        onPointerLeave={() => {
          setHover(null);
          setCursor(null);
        }}
      />
      {cursor && (
        <div className="pointer-events-none absolute bottom-1.5 left-2 rounded bg-white/85 dark:bg-slate-900/85 px-1.5 py-0.5 text-[11px] text-slate-600 dark:text-slate-300 num"
          data-testid="cursor-readout" title={tab?.local ? `x from ${tab.local.x_from}; y from ${tab.local.y_from}` : "sheet coordinates (drawing units)"}>
          {tab?.local ? `${tab.id}: ${sayLocal(tab.local, cursor[0], cursor[1])}` : `sheet x ${cursor[0].toFixed(0)} · y ${cursor[1].toFixed(0)}`}
        </div>
      )}
    </div>
  );
}
