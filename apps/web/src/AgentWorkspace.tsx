import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, type CorpusApiClient, type ProjectView } from '../../../contracts/types/s1';
import type { AgentEvent, AgentResultView, AgentRun, AgentRuntime, AgentScope, AgentSession, AgentTurn } from '../../../contracts/types/agent';
import { AgentReads, agentBusy, agentConfigChanged, mergeTurns, runtimeLabel, scopeKey, transcriptChanged } from './agent-state';

const states: Record<string, string> = { QUEUED: '排队中', RUNNING: '执行中', WAITING_JOB: '等待后台任务', WAITING_REVIEW: '需要核查', CANCELLED: '已取消', SUCCEEDED: '已完成', FAILED: '失败' };
const toolStatus: Record<string, string> = { succeeded: '完成', accepted: '任务已提交', failed: '失败', unknown: '待核查' };
const reasons: Record<string, string> = { MODEL_NOT_CONFIGURED: '尚未配置模型', MODEL_CONFIGURATION_INVALID: '模型配置有误', AGENT_CONFIG_CHANGED: '模型配置已变化，请新建会话', MODEL_AUTH_FAILED: '模型认证失败', MODEL_RATE_LIMITED: '模型请求受限', MODEL_TIMEOUT: '模型响应超时', MODEL_REQUEST_FAILED: '模型调用失败', MODEL_RESPONSE_INVALID: '模型响应格式不支持', SESSION_BUSY: '当前会话正在执行或需要核查', SESSION_SCOPE_CHANGED: '会话范围已变化，请新建会话', AGENT_RUNTIME_UNAVAILABLE: '助手运行配置不可用', LEASE_EXPIRED_NO_CHECKPOINT: '执行中断，需要核查', USER_CANCELLED: '用户已取消', CHECKPOINT_AUTH_CHANGED: '历史材料权限已变化，已停止显示会话', JOB_NOT_SUCCEEDED: '后台任务未成功', JOB_FAILED: '后台任务失败', WAIT_DEADLINE_EXCEEDED: '等待后台任务超时', ACTIVE_DEADLINE_EXCEEDED: '运行超时', CHECKPOINT_RESTORE_FAILED: '会话恢复失败，需要核查', SDK_CONTEXT_UNCERTAIN: '执行上下文不明确，需要核查', CHECKPOINT_NOT_IMPLEMENTED: '缺少可靠会话记录，需要核查', CHECKPOINT_PUBLISHED: '会话记录已保存', REGISTERED_JOBS_PENDING: '已提交后台任务，完成后继续', WAITING_JOB_UNAVAILABLE: '关联后台任务不可访问', WAITING_JOB_MISMATCH: '关联后台任务已变化，需要核查', AGENT_AUTH_REVOKED: '会话授权已撤回', AGENT_RUN_NOT_FOUND: '运行不可访问', AGENT_SESSION_NOT_FOUND: '会话不可访问', IDEMPOTENCY_CONFLICT: '提交内容与此前请求不一致，请重新发送' };
const toolNames: Record<string, string> = { 'account.get': '读取账号', 'projects.list': '项目列表', 'projects.create': '创建项目', 'projects.get': '读取项目', 'materials.list': '材料列表', 'materials.get': '读取材料状态', 'imports.start': '解析 TXT', 'imports.get': '读取解析状态', 'snapshots.create': '建立快照', 'snapshots.get': '读取快照状态', 'corpus.describe': '读取语料状态', 'results.get': '读取结果状态', 'evidence.create': '保存证据', 'evidence.list': '证据列表', 'notes.list': '笔记列表', 'exports.create': '生成导出', 'exports.list': '导出列表', 'exports.get': '读取导出状态', 'jobs.get': '读取任务状态', 'jobs.list': '任务列表', 'jobs.cancel': '取消任务', 'jobs.retry': '重试任务', 'sync.report': '读取同步状态', 'indexes.report': '读取索引状态' };
const resultNames: Record<AgentResultView['kind'], string> = { project: '打开项目', material: '查看材料', snapshot: '打开检索', query: '打开检索', evidence: '查看证据', note: '查看笔记', export: '查看导出', job: '查看任务' };

export function AgentWorkspace({ client, actorId, projects, visible, onOpenResult, onUnauthorized }: {
  client: CorpusApiClient; actorId: string; projects: ProjectView[]; visible: boolean;
  onOpenResult: (result: AgentResultView, scope: AgentScope) => void; onUnauthorized: (error: unknown) => void;
}) {
  const [runtime, setRuntime] = useState<AgentRuntime>();
  const [scope, setScope] = useState<AgentScope>({ scope_kind: 'account' });
  const currentScope = useRef<AgentScope>(scope);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [sessionMore, setSessionMore] = useState<string | null>(null);
  const [session, setSession] = useState<AgentSession>();
  const sessionRef = useRef<AgentSession | undefined>(undefined);
  const [turns, setTurnState] = useState<AgentTurn[]>([]);
  const turnsRef = useRef<AgentTurn[]>([]);
  function setTurns(value: AgentTurn[] | ((previous: AgentTurn[]) => AgentTurn[])) {
    const next = typeof value === 'function' ? value(turnsRef.current) : value;
    turnsRef.current = next; setTurnState(next);
  }
  const [turnMore, setTurnMore] = useState<string | null>(null);
  const [run, setRunState] = useState<AgentRun>();
  const runRef = useRef<AgentRun | undefined>(undefined);
  function setRun(value?: AgentRun) { runRef.current = value; setRunState(value); }
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [configRejectedFor, setConfigRejectedFor] = useState<string>();
  const reads = useRef(new AgentReads()).current;
  const submit = useRef<{ session: string; message: string; key: string } | undefined>(undefined);
  const draft = useRef(new Map<string, string>());
  const messagesLoaded = useRef(false);
  const storageKey = `corpus-agent-session:${actorId}`;

  function remember(value?: AgentSession) {
    sessionRef.current = value; setSession(value);
    if (value) {
      setSessions(items => items.map(item => item.session_id === value.session_id ? value : item));
      localStorage.setItem(storageKey, value.session_id);
    }
    else localStorage.removeItem(storageKey);
  }
  function clearHistory() {
    setConfigRejectedFor(undefined);
    reads.invalidate(); messagesLoaded.current = false; remember(undefined); setTurns([]); setRun(undefined); setEvents([]); setTurnMore(null); submit.current = undefined;
  }
  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.code === 'AGENT_CONFIG_CHANGED') setConfigRejectedFor(sessionRef.current?.session_id);
    if (cause instanceof ApiError && ([401, 403, 404].includes(cause.status) || cause.code === 'CHECKPOINT_AUTH_CHANGED')) {
      clearHistory(); setSessions([]); setSessionMore(null);
      if (cause.status === 401) onUnauthorized(cause);
    }
    setError(cause instanceof ApiError ? reasons[cause.code] || cause.message : cause instanceof Error ? cause.message : '读取失败，请重试');
  }
  async function listSessions(before?: string) {
    const valid = reads.begin('sessions'); const selected = currentScope.current;
    try {
      const page = await client.agentSessions(selected.scope_kind, selected.scope_kind === 'project' ? selected.project_id : undefined, before);
      if (!valid()) return;
      setSessions(items => before ? [...items, ...page.items.filter(item => !items.some(old => old.session_id === item.session_id))] : page.items);
      setSessionMore(page.next_before);
    } catch (cause) { if (valid()) fail(cause); }
  }
  async function readSession(id: string, before?: string) {
    const valid = reads.begin('transcript');
    try {
      const fresh = await client.agentSession(id);
      const [messages, runs] = await Promise.all([client.agentMessages(id, before), client.agentRuns(id)]);
      const latest = fresh.active_run_id ? await client.agentRun(fresh.active_run_id) : runs.items[0];
      const timeline: AgentEvent[] = [];
      if (latest) {
        let after = 0;
        do {
          const page = await client.agentEvents(latest.run_id, after);
          timeline.push(...page.items);
          if (!page.items.length || page.next_after <= after) break;
          after = page.next_after;
        } while (after < latest.event_sequence && valid());
      }
      if (!valid() || sessionRef.current?.session_id !== id) return;
      remember(fresh); setRun(latest); setEvents(timeline);
      setTurns(previous => mergeTurns(previous, messages.items));
      if (before || !messagesLoaded.current) setTurnMore(messages.next_before);
      messagesLoaded.current = true;
    } catch (cause) { if (valid()) fail(cause); }
  }
  async function selectSession(value: AgentSession) {
    clearHistory(); setError(''); currentScope.current = value.scope; setScope(value.scope); remember(value);
    setLoading(true); await readSession(value.session_id); setLoading(false);
  }
  function changeScope(value: string) {
    draft.current.set(scopeKey(currentScope.current), message);
    clearHistory(); setSessions([]); setError('');
    const next: AgentScope = value === 'account' ? { scope_kind: 'account' } : { scope_kind: 'project', project_id: value, snapshot_ids: [], material_revision_ids: [], alignment_overlay_revision: null, result_refs: [] };
    currentScope.current = next; setScope(next); setMessage(draft.current.get(value) ?? '');
    void listSessions();
  }
  async function refresh() {
    setError('');
    const valid = reads.begin('runtime');
    try { const value = await client.agentRuntime(); if (valid()) setRuntime(value); }
    catch (cause) { if (valid()) { setRuntime(undefined); fail(cause); } }
    await listSessions();
    if (sessionRef.current) await readSession(sessionRef.current.session_id);
  }
  useEffect(() => {
    let mounted = true;
    void (async () => {
      try {
        const value = await client.agentRuntime(); if (!mounted) return; setRuntime(value);
        const remembered = localStorage.getItem(storageKey);
        if (remembered) {
          const saved = await client.agentSession(remembered); if (!mounted) return;
          if (saved.scope.scope_kind !== 'platform') {
            currentScope.current = saved.scope; setScope(saved.scope); remember(saved); await readSession(saved.session_id);
          } else localStorage.removeItem(storageKey);
        }
        if (mounted) await listSessions();
      } catch (cause) { if (mounted) fail(cause); }
      finally { if (mounted) setLoading(false); }
    })();
    return () => { mounted = false; reads.invalidate(); };
  }, []);
  async function poll() {
    const valid = reads.begin('poll'); const selected = sessionRef.current;
    try {
      const config = await client.agentRuntime(); if (!valid()) return; setRuntime(config);
      if (!selected) return;
      const fresh = await client.agentSession(selected.session_id);
      const runId = fresh.active_run_id ?? runRef.current?.run_id;
      const current = runId ? await client.agentRun(runId) : undefined;
      const historical = [...new Set(turnsRef.current.map(turn => turn.run_id))].filter(id => id !== runId);
      for (let offset = 0; offset < historical.length && valid(); offset += 4) {
        await Promise.all(historical.slice(offset, offset + 4).map(id => client.agentRun(id)));
      }
      if (!valid() || sessionRef.current?.session_id !== selected.session_id) return;
      const previous = runRef.current;
      const changed = transcriptChanged(previous, current);
      remember(fresh); setRun(current);
      // Terminal history is reauthorized via session/run metadata; full SDK
      // transcript projections are fetched only on a real event/state change.
      if (changed) await readSession(selected.session_id);
    } catch (cause) { if (valid()) fail(cause); }
  }
  useEffect(() => {
    if (!visible || loading) return;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight || busy) return;
      inFlight = true; void poll().finally(() => { inFlight = false; });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [visible, loading, busy]);

  async function send(event: FormEvent) {
    event.preventDefault(); if (busy || !runtime?.can_submit || configChanged || !message.trim() || agentBusy(run)) return;
    setBusy(true); setError(''); const valid = reads.begin('mutation');
    try {
      let selected = sessionRef.current;
      if (!selected) { selected = await client.createAgentSession(currentScope.current); if (!valid()) return; remember(selected); }
      if (!submit.current || submit.current.message !== message || submit.current.session !== selected.session_id) {
        submit.current = { session: selected.session_id, message, key: crypto.randomUUID() };
      }
      const accepted = await client.createAgentRun(selected.session_id, { request_key: submit.current.key, message, scope_digest: selected.scope_digest });
      if (!valid()) return;
      setRun(accepted); setMessage(''); draft.current.delete(scopeKey(currentScope.current)); submit.current = undefined;
      await readSession(selected.session_id); await listSessions();
    } catch (cause) { if (valid()) fail(cause); }
    finally { setBusy(false); }
  }
  async function cancel() {
    if (!run) return; setBusy(true); setError('');
    try { setRun(await client.cancelAgentRun(run.run_id)); if (sessionRef.current) await readSession(sessionRef.current.session_id); }
    catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  const configChanged = agentConfigChanged(runtime, session) || (!!session && configRejectedFor === session.session_id);
  return <section className="agent-workspace" hidden={!visible}>
    <div className="section-title"><h2>研究助手</h2><button disabled={busy || loading} onClick={() => void refresh()}>刷新</button></div>
    <p role="status">{runtimeLabel(runtime)}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="workspace"><aside>
      <label>会话范围<select disabled={busy || loading} value={scopeKey(scope)} onChange={event => changeScope(event.target.value)}><option value="account">我的账号</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <button disabled={busy || loading} onClick={() => { clearHistory(); setError(''); }}>新会话</button>
      <h2>会话记录</h2>
      {sessions.length ? <nav aria-label="助手会话">{sessions.map(item => <button disabled={busy} className={session?.session_id === item.session_id ? 'selected' : ''} key={item.session_id} onClick={() => void selectSession(item)}>{new Date(item.created_at).toLocaleString()}{item.active_run_id ? ' · 有运行' : ''}</button>)}</nav> : <p>暂无会话</p>}
      {sessionMore && <button disabled={busy} onClick={() => void listSessions(sessionMore)}>查看更多会话</button>}
    </aside><div className="content">
      {configChanged && <p role="status">此会话使用{session?.config_id === 'local-fixture-v1' ? '本地流程测试' : '此前模型配置'}，仅可查看历史。请新建会话后发送。</p>}
      {!configChanged && session?.config_id === 'local-fixture-v1' && runtime?.mode !== 'fixture' && <p>历史会话：本地流程测试</p>}
      {turnMore && <button disabled={busy} onClick={() => session && void readSession(session.session_id, turnMore)}>更早的消息</button>}
      {loading ? <p>正在读取会话…</p> : turns.length === 0 ? <p>暂无消息</p> : <div className="agent-transcript">{turns.map(turn => <article key={turn.run_id}>
        <h3>你</h3><p className="sentence-text">{turn.user_message}</p>
        {turn.assistant_messages.map(answer => <div key={answer.id}><h3>助手</h3><p className="sentence-text">{answer.text}</p></div>)}
        {turn.tools.length > 0 && <ul className="agent-tools">{turn.tools.map(tool => <li key={tool.invocation_id}><span>{toolNames[tool.tool_name] || tool.tool_name} · {toolStatus[tool.status] || tool.status}</span>{tool.result_view && <button onClick={() => onOpenResult(tool.result_view!, scope)}>{resultNames[tool.result_view.kind]}</button>}</li>)}</ul>}
        <p>{states[turn.state]}</p>
      </article>)}</div>}
      {run && <section aria-label="当前运行"><div className="actions"><h3>{states[run.state]}</h3>{agentBusy(run) && <button disabled={busy} onClick={() => void cancel()}>取消运行</button>}</div>
        {run.reason && <p>{reasons[run.reason] || '运行需要核查，请查看运行记录'}</p>}
        {run.waiting_jobs.length > 0 && <ul>{run.waiting_jobs.map(job => <li key={job.job_id}>{toolNames[job.report_tool] || job.report_tool} · {states[job.state] || job.state}</li>)}</ul>}
        <details><summary>运行记录</summary><p className="digest">{run.run_id}</p>{run.reason && <p>{run.reason}</p>}<ul>{events.map(event => <li key={event.event_id}>{event.kind} · {new Date(event.created_at).toLocaleTimeString()}</li>)}</ul></details>
      </section>}
      <form onSubmit={event => void send(event)}><label>消息<textarea maxLength={8000} value={message} disabled={busy} onChange={event => setMessage(event.target.value)} /></label><button disabled={busy || loading || !runtime?.can_submit || configChanged || !message.trim() || agentBusy(run)}>{busy ? '提交中…' : '发送'}</button></form>
    </div></div>
  </section>;
}
