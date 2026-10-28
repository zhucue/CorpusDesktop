import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Corpus, type Job } from "../src/api";
import { jobTitle, progressText } from "../src/components/global/TaskTray";
import { corpusLanguages, corpusProfile } from "../src/features/corpora/CorpusMeta";
import { draftFrom, metadataFromDraft } from "../src/features/corpora/MetadataInput";
import { dedupeFiles } from "../src/features/corpora/UploadDialog";

const job = (over: Partial<Job>): Job => ({
  id: "28e7479f-0000",
  project_id: "p1",
  kind: "stats",
  state: "succeeded",
  progress: { done: 0, total: null, message: "计算" },
  result: { stat_id: "s1" },
  error: null,
  created_at: "2026-10-28T10:00:00Z",
  finished_at: "2026-10-28T10:00:05Z",
  ...over,
});

describe("job text", () => {
  it("names what a finished statistic computed instead of 已处理 0", () => {
    const j = job({ summary: "频次 · QA 中英平行 TMX" });
    expect(jobTitle(j)).toBe("频次 · QA 中英平行 TMX");
    expect(progressText(j)).toBe("已完成");
  });

  it("shows the queue position and progress units", () => {
    expect(progressText(job({ state: "queued", queue_ahead: 3 }))).toBe("排队中 · 前面还有 3 个任务");
    expect(progressText(job({ state: "queued", queue_ahead: 0 }))).toBe("排队中 · 下一个执行");
    const running = job({ kind: "import", state: "running", summary: "作文：a.docx", progress: { done: 100, total: 228, message: "分句与标注", unit: "字" } });
    expect(jobTitle(running)).toBe("导入 · 作文：a.docx");
    expect(progressText(running)).toBe("100 / 228 字");
    // older jobs carry the unit in the message
    expect(progressText(job({ state: "running", progress: { done: 2, total: 5, message: "建索引（文档）" } }))).toBe("2 / 5 文档");
  });
});

describe("upload metadata rows", () => {
  it("turns rows into metadata with numbers, and reports bad rows", () => {
    const rows = (r: [string, string][]) => ({ mode: "rows" as const, rows: r.map(([key, value]) => ({ key, value })), json: "" });
    expect(metadataFromDraft(rows([["year", "2020"], ["genre", "新闻"], ["code", "007"], ["", ""]]))).toEqual({ year: 2020, genre: "新闻", code: "007" });
    expect(() => metadataFromDraft(rows([["", "x"]]))).toThrow("第 1 行缺少字段名");
    expect(() => metadataFromDraft(rows([["a", "1"], ["a", "2"]]))).toThrow("字段「a」重复");
    expect(() => metadataFromDraft({ mode: "json", rows: [], json: "[1]" })).toThrow("元数据须为 JSON 对象");
    expect(draftFrom({ a: { nested: 1 } }).mode).toBe("json");
  });

  it("drops a file chosen twice", () => {
    const f = (name: string, size: number) => ({ uid: `${name}${Math.random()}`, name, size });
    const { files, dropped } = dedupeFiles([f("a.txt", 10), f("a.txt", 10), f("a.txt", 11)]);
    expect(files.map((x) => x.size)).toEqual([10, 11]);
    expect(dropped).toEqual(["a.txt"]);
  });
});

describe("corpus profile", () => {
  const corpus = (over: Partial<Corpus>): Corpus => ({
    id: "c",
    project_id: null,
    name: "Tatoeba",
    language: "zh",
    description: "",
    parallel: true,
    status: "ready",
    error: null,
    stats: { documents: 2, sentences: 10, tokens: 50, pairs: 5 },
    index_version: "abc",
    created_at: "",
    ...over,
  });
  it("shows zh-en, script and tag set", () => {
    const c = corpus({ meta: { languages: ["en", "zh"], script: "traditional", tagset: "upos" } });
    expect(corpusLanguages(c)).toBe("zh-en");
    expect(corpusProfile(c)).toEqual(["zh-en", "繁体", "UPOS"]);
    expect(corpusLanguages(corpus({ language: "auto", meta: {} }))).toBe("待识别");
  });
});

describe("unavailable backend", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("maps 502 and failed connections to one Chinese message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" })));
    await expect(api.post("/layers/x/annotations", {})).rejects.toThrow("服务暂时不可用，本次修改未保存，请重试");
    await expect(api.get("/corpora")).rejects.toThrow("服务暂时不可用，请稍后重试");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api.patch("/x", {})).rejects.toMatchObject({ code: "UNAVAILABLE", status: 0 });
    // a backend error with its own code keeps it
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "MODEL_NOT_CONFIGURED", message: "x" } }), { status: 503 })));
    await expect(api.get("/x")).rejects.toMatchObject({ code: "MODEL_NOT_CONFIGURED" });
  });
});
