import { describe, expect, it } from "vitest";
import { parseFastaByChain } from "./fastaByChain";

describe("parseFastaByChain", () => {
  it("reads '>Chain X' headers and joins wrapped lines", () => {
    const m = parseFastaByChain(">Chain A\nACD\nEFG\n>Chain_B\nMNP\n");
    expect(m.get("A")).toBe("ACDEFG");
    expect(m.get("B")).toBe("MNP");
  });

  it("falls back to the first header token", () => {
    expect(parseFastaByChain(">sp|P1|X\nAAA").get("sp|P1|X")).toBe("AAA");
  });

  it("returns an empty map for empty input", () => {
    expect(parseFastaByChain("").size).toBe(0);
  });
});
