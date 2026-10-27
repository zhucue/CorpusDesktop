import type { AgentRun, AgentRuntime, AgentScope, AgentSession, AgentTurn } from '../../../contracts/types/agent.ts';

/** A selection change or denied read invalidates every outstanding page read. */
export class AgentReads {
  private generation = 0;
  private sequences = new Map<string, number>();
  invalidate() { this.generation++; this.sequences.clear(); }
  begin(channel: string) {
    const generation = this.generation;
    const sequence = (this.sequences.get(channel) ?? 0) + 1;
    this.sequences.set(channel, sequence);
    return () => this.generation === generation && this.sequences.get(channel) === sequence;
  }
}
export const agentBusy = (run?: AgentRun) => !!run && ['QUEUED', 'RUNNING', 'WAITING_JOB', 'WAITING_REVIEW'].includes(run.state);
export const transcriptChanged = (previous: AgentRun | undefined, current: AgentRun | undefined) => !!current &&
  (!previous || current.run_id !== previous.run_id || current.state !== previous.state || current.event_sequence !== previous.event_sequence);
export const scopeKey = (scope: AgentScope) => scope.scope_kind === 'project' ? scope.project_id : scope.scope_kind;
export const agentConfigChanged = (runtime?: AgentRuntime, session?: AgentSession) =>
  !!runtime?.config_id && !!session && runtime.config_id !== session.config_id;
export function runtimeLabel(runtime?: AgentRuntime) {
  if (!runtime) return '正在读取运行配置…';
  if (runtime.mode === 'fixture') return '本地流程测试';
  if (runtime.reason === 'MODEL_CONFIGURATION_INVALID') return '模型配置有误';
  if (runtime.mode === 'openai-compatible' && runtime.can_submit) return `已配置模型 ${runtime.runtime_manifest.model}`;
  return '尚未配置模型';
}
export function mergeTurns(previous: AgentTurn[], incoming: AgentTurn[]) {
  const turns = new Map(previous.map(turn => [turn.run_id, turn]));
  for (const turn of incoming) turns.set(turn.run_id, turn);
  return [...turns.values()].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.run_id.localeCompare(b.run_id));
}
