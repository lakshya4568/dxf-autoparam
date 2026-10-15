import { describe, expect, it } from "vitest";
import { DARK, dashPx, fontFamily, LIGHT, lineWidthPx, luminance, strokeColor, strokeKey } from "../src/canvas/styles";

const rgb = (c: string): [number, number, number] => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];

describe("colour", () => {
  it("ACI 7 is the theme's foreground", () => {
    expect(strokeColor({ c: "#ffffff", w: 0.25, lt: "CONTINUOUS", fg: 1 }, LIGHT)).toBe(LIGHT.fg);
    expect(strokeColor({ c: "#ffffff", w: 0.25, lt: "CONTINUOUS", fg: 1 }, DARK)).toBe(DARK.fg);
  });

  it("a colour too light for a white sheet is darkened keeping its hue", () => {
    const out = rgb(strokeColor({ c: "#ffff00", w: 0.25, lt: "CONTINUOUS" }, LIGHT));
    expect(luminance(out)).toBeLessThanOrEqual(0.63);
    expect(out[0]).toBe(out[1]); // yellow stays yellow
    expect(out[2]).toBe(0);
  });

  it("a readable colour is kept as filed", () => {
    expect(strokeColor({ c: "#ff0000", w: 0.25, lt: "CONTINUOUS" }, LIGHT)).toBe("#ff0000");
  });

  it("without a style the line is drawn in the foreground", () => {
    expect(strokeColor(undefined, DARK)).toBe(DARK.fg);
  });
});

describe("linetype and weight", () => {
  it("a dash pattern scales with the zoom", () => {
    const st = { c: "#000000", w: 0.25, lt: "DASHED", d: [12.7, -6.35] };
    expect(dashPx(st, 1)).toEqual([12.7, 6.35]);
    expect(dashPx(st, 2)).toEqual([25.4, 12.7]);
  });

  it("a pattern too fine to see draws continuous, as CAD does zoomed out", () => {
    expect(dashPx({ c: "#000000", w: 0.25, lt: "DOT", d: [0, -6.35] }, 0.1)).toBeNull();
    expect(dashPx({ c: "#000000", w: 0.25, lt: "CONTINUOUS" }, 5)).toBeNull();
  });

  it("a dot keeps a visible length", () => {
    const d = dashPx({ c: "#000000", w: 0.25, lt: "DOT", d: [0, -6.35] }, 2)!;
    expect(d[0]).toBeGreaterThan(0);
  });

  it("lineweights are screen pixels, never below one", () => {
    expect(lineWidthPx({ c: "#000", w: 0.05, lt: "C" }, LIGHT)).toBe(1);
    expect(lineWidthPx({ c: "#000", w: 0.7, lt: "C" }, LIGHT)).toBeGreaterThan(lineWidthPx({ c: "#000", w: 0.35, lt: "C" }, LIGHT));
    expect(lineWidthPx({ c: "#000", w: 5, lt: "C" }, LIGHT)).toBe(6);
  });

  it("fonts map to a close system family", () => {
    expect(fontFamily({ c: "#000", w: 0.25, lt: "C", f: "romans.shx" })).toMatch(/Narrow/);
    expect(fontFamily({ c: "#000", w: 0.25, lt: "C", f: "Times New Roman" })).toMatch(/Times/);
    expect(fontFamily(undefined)).toMatch(/Arial/);
  });

  it("strokes of equal colour, width and dash share a key", () => {
    expect(strokeKey(undefined, [2, 1], "#000", 1)).toBe(strokeKey(undefined, [2, 1], "#000", 1));
    expect(strokeKey(undefined, null, "#000", 1)).not.toBe(strokeKey(undefined, [2, 1], "#000", 1));
  });
});
