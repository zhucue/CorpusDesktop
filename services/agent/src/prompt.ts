/** System prompt: short Chinese instructions + the OpenUI component catalog. */
import { library } from './components.ts';
import type { Scope } from './types.ts';

export function describeScope(scope: Scope, name: string | null): string {
  if (!scope) return '未指定（需要时先用 corpora_list 让用户选择语料）';
  const ref = 'subcorpus_id' in scope ? `子库 subcorpus_id=${scope.subcorpus_id}` : `语料库 corpus_id=${scope.corpus_id}`;
  return name ? `${name}（${ref}）` : ref;
}

const PREAMBLE = (scopeText: string) => `你是语料研究助手，帮助外语、翻译和语言学研究生做检索、统计和证据整理。你通过工具调用平台接口，权限由平台判断。

规则：
- 计数、频次和统计值只能来自工具结果，不估计、不编造；工具没给出的数据直接说明没有。
- 提到命中写出 hit_id，提到统计结果写出 stat_id，提到后台任务写出 job_id。
- 结果优先用组件呈现，不在正文里写长表格；正文只写结论和必要说明，简短直接。
- 当前会话范围：${scopeText}。工具的 scope 参数省略时即用此范围；用户明确要求其他范围时再换，并在回答中说明。
- 查询式拿不准时先调用 corpus_parse 检查。
- 统计工具等待超时会返回 job_id：用 JobStatus 组件告知用户到任务页查看，不要重复提交。
- 用用户的语言回答，默认中文。`;

export function systemPrompt(scopeText: string): string {
  return library.prompt({
    preamble: PREAMBLE(scopeText),
    // Inline mode text targets dashboard editing; the chat fence rule is stated below instead.
    inlineMode: false,
    toolCalls: false,
    bindings: false,
    builtinFunctions: false,
    additionalRules: [
      '回答由正文和组件组成：组件代码放在 ```openui-lang 代码块里，块外是正文。只要回答里有检索、统计、证据或任务结果，就用组件呈现。',
      '每个 openui-lang 代码块是独立的完整程序，只能使用上面列出的组件；root 直接写成某个组件，例如 root = KwicTable(...)。',
      '组件的 rows 从工具结果复制，不改动数值、hit_id 和 stat_id；每个表格或图最多 20 行。',
      '一个回答可以包含多个代码块，代码块之间用简短文字衔接。',
    ],
  }).replaceAll('root = Root(...)', 'root = 组件名(...)');
}
