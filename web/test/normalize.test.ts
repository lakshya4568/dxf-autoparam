// A group of entities arrived as {} where the page iterated a list: the click on a value silently did nothing. Whatever shape a group
// has, the page gets numbers, and nothing throws.
import { describe, expect, it } from "vitest";
import { entityList, entitySet } from "../src/api/normalize";

describe("entityList / entitySet", () => {
  it("reads an empty object as an empty group (the shape that broke the Values panel)", () => {
    expect(entityList({})).toEqual([]);
    expect(entitySet({})).toEqual(new Set());
  });

  it("reads null, undefined and unreadable values as empty", () => {
    for (const v of [null, undefined, "x", true, 3.5, NaN, Symbol.iterator, () => 1]) expect(entityList(v)).toEqual([]);
  });

  it("reads a list of numbers", () => {
    expect(entityList([3, 1, 2])).toEqual([3, 1, 2]);
    expect(entityList([])).toEqual([]);
  });

  it("reads the engine's real shape: label → entities", () => {
    expect(entitySet({ "Foundation (keep_fixed)": [4, 5], "WingLeft (follow)": [9] })).toEqual(new Set([4, 5, 9]));
    expect(entitySet({ a: [], b: [] })).toEqual(new Set());
  });

  it("reads the list-of-groups shape the type used to claim", () => {
    expect(entitySet([{ label: "Foundation", set: [1, 2] }, { label: "Wing", set: [7] }])).toEqual(new Set([1, 2, 7]));
  });

  it("flattens lists of lists and mixed shapes, and drops what is not an entity index", () => {
    expect(entitySet([[1, 2], 3, { x: [4] }, "no", null, 5.5, [[6]]])).toEqual(new Set([1, 2, 3, 4, 6]));
  });

  it("does not follow a structure forever", () => {
    let deep: unknown = [1];
    for (let i = 0; i < 50; i++) deep = [deep];
    expect(() => entityList(deep)).not.toThrow();
    const loop: Record<string, unknown> = { a: [1] };
    loop.self = loop;
    expect(() => entityList(loop)).not.toThrow();
  });
});
