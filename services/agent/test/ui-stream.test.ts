import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FenceSplitter, type Chunk } from '../src/ui-stream.ts';

function split(text: string, size: number) {
  const chunks: Chunk[] = [];
  const splitter = new FenceSplitter(chunk => chunks.push(chunk));
  for (let i = 0; i < text.length; i += size) splitter.push(text.slice(i, i + size));
  splitter.end();
  // merge like the runner: same kind extends, a new ui block starts a new part
  const parts: { kind: string; text: string }[] = [];
  for (const chunk of chunks) {
    const last = parts.at(-1);
    if (last && last.kind === chunk.kind && !(chunk.kind === 'ui' && chunk.newBlock)) last.text += chunk.text;
    else parts.push({ kind: chunk.kind, text: chunk.text });
  }
  return parts;
}

const SAMPLE = '结论如下：\n```openui-lang\nroot = Callout("info", "a")\n```\n```openui-lang\nroot = Callout("warning", "b")\n```\n代码示例：\n```python\nprint(1)\n```\n结束';

test('fences split prose and OpenUI Lang regardless of chunk size', () => {
  const expected = [
    { kind: 'text', text: '结论如下：\n' },
    { kind: 'ui', text: 'root = Callout("info", "a")\n' },
    { kind: 'ui', text: 'root = Callout("warning", "b")\n' },
    { kind: 'text', text: '代码示例：\n```python\nprint(1)\n```\n结束' },
  ];
  for (const size of [1, 2, 3, 5, 8, 13, SAMPLE.length]) assert.deepEqual(split(SAMPLE, size), expected, `chunk size ${size}`);
});

test('unclosed fence at end of stream still yields the ui part', () => {
  assert.deepEqual(split('看这里\n```openui-lang\nroot = Callout("info", "x")', 4), [
    { kind: 'text', text: '看这里\n' },
    { kind: 'ui', text: 'root = Callout("info", "x")' },
  ]);
});
