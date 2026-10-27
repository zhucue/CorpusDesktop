import { describe, expect, it } from "vitest";
import { SseParser, type SseEvent } from "../src/features/assistant/sse";

const stream =
  'event: start\ndata: {"message_id":"m1"}\n\n' +
  ": ping\n\n" +
  'event: text\r\ndata: {"delta":"你好","part":0}\r\n\r\n' +
  "event: ui\ndata: line one\ndata: line two\n\n" +
  'event: done\ndata: {"message":{"id":"m1"}}\n\n';

describe("SseParser", () => {
  it("parses a whole stream", () => {
    const p = new SseParser();
    const out = [...p.push(stream), ...p.flush()];
    expect(out.map((e) => e.event)).toEqual(["start", "text", "ui", "done"]);
    expect(JSON.parse(out[1].data)).toEqual({ delta: "你好", part: 0 });
    expect(out[2].data).toBe("line one\nline two");
  });

  it("merges chunks split at every position, including inside CRLF", () => {
    for (let size = 1; size <= 7; size++) {
      const p = new SseParser();
      const out: SseEvent[] = [];
      for (let i = 0; i < stream.length; i += size) out.push(...p.push(stream.slice(i, i + size)));
      out.push(...p.flush());
      expect(out.map((e) => e.event)).toEqual(["start", "text", "ui", "done"]);
      expect(JSON.parse(out[1].data).delta).toBe("你好");
    }
  });

  it("ignores comments and emits a trailing event on flush", () => {
    const p = new SseParser();
    expect(p.push(': ping\n\nevent: error\ndata: {"code":"MODEL_TIMEOUT"}')).toEqual([]);
    expect(p.flush()).toEqual([{ event: "error", data: '{"code":"MODEL_TIMEOUT"}' }]);
  });

  it("keeps a lone CR until the next chunk decides CRLF", () => {
    const p = new SseParser();
    expect(p.push("event: text\r")).toEqual([]);
    expect(p.push("\ndata: x\r")).toEqual([]);
    expect(p.push("\n\r\n")).toEqual([{ event: "text", data: "x" }]);
  });
});
