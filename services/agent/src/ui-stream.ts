/**
 * Splits streamed assistant text into prose and OpenUI Lang. In inline mode the
 * model wraps OpenUI Lang in ```openui-lang fences; text outside fences is prose.
 * Fence lines themselves are dropped. Each fence opens a new ui part.
 */
export type Chunk = { kind: 'text' | 'ui'; text: string; newBlock: boolean };

const OPEN = /^\s{0,3}```\s*(openui-lang|openui)\s*$/i;
const CLOSE = /^\s{0,3}```\s*$/;
// A partial line that could still become a fence line; hold it until the line ends.
const MAYBE_FENCE = /^\s{0,3}(`{0,2}|```.*)$/;

export class FenceSplitter {
  private mode: 'text' | 'ui' = 'text';
  private buffer = '';
  private lineStart = true;
  private newBlock = false;
  private readonly emit: (chunk: Chunk) => void;

  constructor(emit: (chunk: Chunk) => void) {
    this.emit = emit;
  }

  push(delta: string) {
    this.buffer += delta;
    this.drain(false);
  }

  end() {
    this.drain(true);
    this.mode = 'text';
    this.lineStart = true;
  }

  private out(text: string) {
    if (!text) return;
    this.emit({ kind: this.mode, text, newBlock: this.newBlock });
    this.newBlock = false;
  }

  private drain(final: boolean) {
    while (this.buffer) {
      const newline = this.buffer.indexOf('\n');
      if (!this.lineStart) {
        if (newline === -1) { this.out(this.buffer); this.buffer = ''; return; }
        this.out(this.buffer.slice(0, newline + 1));
        this.buffer = this.buffer.slice(newline + 1);
        this.lineStart = true;
        continue;
      }
      if (newline === -1 && !final) {
        if (MAYBE_FENCE.test(this.buffer)) return;
        this.out(this.buffer);
        this.buffer = '';
        this.lineStart = false;
        return;
      }
      const line = newline === -1 ? this.buffer : this.buffer.slice(0, newline);
      const rest = newline === -1 ? '' : this.buffer.slice(newline + 1);
      if (this.mode === 'text' && OPEN.test(line)) {
        this.mode = 'ui';
        this.newBlock = true;
      } else if (this.mode === 'ui' && CLOSE.test(line)) {
        this.mode = 'text';
        this.newBlock = false;
      } else {
        this.out(newline === -1 ? line : line + '\n');
      }
      this.buffer = rest;
    }
  }
}
