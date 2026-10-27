export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental text/event-stream parser. Feed decoded chunks in any split; complete events come out.
 * Handles CRLF/CR/LF, multi-line data, comment lines (": ping") and a trailing event without blank line on flush().
 */
export class SseParser {
  private buf = "";
  private event = "";
  private data: string[] = [];

  push(chunk: string): SseEvent[] {
    this.buf += chunk;
    const out: SseEvent[] = [];
    for (;;) {
      const m = /\r\n|\r|\n/.exec(this.buf);
      if (!m) break;
      // A lone "\r" at the end might be the first half of "\r\n": wait for more input.
      if (m[0] === "\r" && m.index === this.buf.length - 1) break;
      const line = this.buf.slice(0, m.index);
      this.buf = this.buf.slice(m.index + m[0].length);
      this.line(line, out);
    }
    return out;
  }

  flush(): SseEvent[] {
    const out: SseEvent[] = [];
    if (this.buf) {
      this.line(this.buf, out);
      this.buf = "";
    }
    this.line("", out);
    return out;
  }

  private line(line: string, out: SseEvent[]) {
    if (line === "") {
      if (this.data.length) out.push({ event: this.event || "message", data: this.data.join("\n") });
      this.event = "";
      this.data = [];
      return;
    }
    if (line.startsWith(":")) return;
    const i = line.indexOf(":");
    const field = i < 0 ? line : line.slice(0, i);
    let value = i < 0 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
  }
}

/** Read a fetch body as SSE events. */
export async function readSse(body: ReadableStream<Uint8Array>, onEvent: (e: SseEvent) => void, signal?: AbortSignal): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      if (signal?.aborted) break;
      const { value, done } = await reader.read();
      if (done) break;
      for (const e of parser.push(decoder.decode(value, { stream: true }))) onEvent(e);
    }
    for (const e of parser.push(decoder.decode())) onEvent(e);
    for (const e of parser.flush()) onEvent(e);
  } finally {
    reader.releaseLock();
  }
}
