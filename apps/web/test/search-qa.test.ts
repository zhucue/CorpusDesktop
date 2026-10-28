import { describe, expect, it } from "vitest";
import { distributionFields, fieldLabel, internalField } from "../src/features/search/fields";
import { convertScript, guessScript } from "../src/features/search/script";

describe("search page helpers (QA 2026-10-28)", () => {
  it("converts between simplified and traditional for the zero-hit hint", () => {
    expect(convertScript("为", "traditional")).toBe("為");
    expect(convertScript("中国/PROPN", "traditional")).toBe("中國/PROPN");
    expect(convertScript("與時並進", "simplified")).toBe("与时并进");
    expect(convertScript("语言 +文化", "traditional")).toBe("語言 +文化");
  });

  it("guesses the script of a sample", () => {
    expect(guessScript("該劇兩位編劇在寫劇本時，幾乎參考了所有有關的資料")).toBe("traditional");
    expect(guessScript("该剧两位编剧在写剧本时，几乎参考了所有有关的资料")).toBe("simplified");
    expect(guessScript("文化")).toBeNull();
  });

  it("orders distribution fields time / genre first and hides ids", () => {
    const fields = distributionFields([
      { field: "page_id", type: "number" },
      { field: "part", type: "number", values: [1] },
      { field: "tatoeba_lang", type: "string", values: ["cmn", "eng"] },
      { field: "genre", type: "string", values: ["新闻", "小说"] },
      { field: "year", type: "number" },
      { field: "url", type: "string" },
      { field: "dump", type: "string", values: ["20261001"] },
    ]);
    expect(fields).toEqual(["year", "genre", "position"]);
    expect(fieldLabel("year")).toBe("年份");
    expect(internalField("revision_id") && internalField("part") && !internalField("genre")).toBe(true);
  });
});
