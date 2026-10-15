// How a resolved CAD style is drawn on this canvas: colour (ACI 7 in the theme's foreground; a colour too light to read on a
// light background darkened, keeping its hue, when "contrast-safe" is on), lineweight in pixels, the linetype's dash pattern
// scaled with the zoom (a pattern finer than a few pixels draws as a line, as CAD does when zoomed out), and the font.
import type { Style } from "../api/types";

export interface Theme {
  dark: boolean;
  bg: string;
  fg: string;
  contrastSafe: boolean;
  lineScale: number; // pixels per 0.25 mm of lineweight (CAD shows lineweights at screen size, not drawing size)
}

export const LIGHT: Theme = { dark: false, bg: "#ffffff", fg: "#1f2933", contrastSafe: true, lineScale: 1 };
export const DARK: Theme = { dark: true, bg: "#0f141a", fg: "#e8edf2", contrastSafe: true, lineScale: 1 };

function hexToRgb(c: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})/i.exec(c);
  if (!m) return [128, 128, 128];
  const v = parseInt(m[1], 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

const toHex = (r: number, g: number, b: number) => "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");

export function luminance([r, g, b]: [number, number, number]): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/** The colour a style is drawn in on this theme. */
export function strokeColor(style: Style | undefined, theme: Theme): string {
  if (!style) return theme.fg;
  if (style.fg) return theme.fg;
  let rgb = hexToRgb(style.c);
  if (theme.contrastSafe) {
    const lum = luminance(rgb);
    if (!theme.dark && lum > 0.62) {
      const k = 0.62 / lum;
      rgb = [rgb[0] * k, rgb[1] * k, rgb[2] * k];
    } else if (theme.dark && lum < 0.18) {
      const k = 0.18 / Math.max(lum, 0.01);
      rgb = [Math.min(255, rgb[0] * k + 40), Math.min(255, rgb[1] * k + 40), Math.min(255, rgb[2] * k + 40)];
    }
  }
  return toHex(rgb[0], rgb[1], rgb[2]);
}

export function alphaOf(style: Style | undefined): number {
  return style?.a ?? 1;
}

/** Lineweight in pixels: CAD displays 0.25 mm as one pixel; heavier pens a little heavier; never below one pixel. */
export function lineWidthPx(style: Style | undefined, theme: Theme): number {
  const lw = style?.w ?? 0.25;
  return Math.max(1, Math.min(6, (lw / 0.25) * theme.lineScale * 0.9));
}

/** The dash pattern in pixels for the canvas (dash, gap, …; a dot is a short dash), or null for a continuous line. */
export function dashPx(style: Style | undefined, pxPerUnit: number): number[] | null {
  const d = style?.d;
  if (!d || !d.length) return null;
  const px = d.map((v) => Math.abs(v) * pxPerUnit);
  const total = px.reduce((a, b) => a + b, 0);
  if (total < 3) return null; // too fine to see: drawn continuous, as CAD does when zoomed far out
  return px.map((v, k) => (k % 2 === 0 ? Math.max(v, 0.6) : Math.max(v, 0.8)));
}

// the single-stroke SHX fonts first: romans.shx is "Roman Simplex", a plain stroke font, not a serif face
const FONT: [RegExp, string][] = [
  [/narrow|condensed|isocp|simplex|romans|txt/i, '"Arial Narrow", "Helvetica Neue", Arial, sans-serif'],
  [/times|roman|serif/i, '"Times New Roman", Times, serif'],
  [/courier|mono/i, '"Courier New", monospace'],
];

export function fontFamily(style: Style | undefined): string {
  const f = style?.f ?? "";
  for (const [re, family] of FONT) if (re.test(f)) return family;
  return "Arial, Helvetica, sans-serif";
}

/** A key that groups primitives drawn with the same stroke (one canvas path per key per frame). */
export function strokeKey(style: Style | undefined, dash: number[] | null, color: string, width: number): string {
  return `${color}|${width.toFixed(2)}|${dash ? dash.map((v) => v.toFixed(1)).join(",") : "-"}|${alphaOf(style)}`;
}
