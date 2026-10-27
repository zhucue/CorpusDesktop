import { useEffect, useRef, useState } from 'react';
import { ApiError, CorpusApiClient } from '../../../contracts/types/s1';
import type { SyncRunList, SyncRunView } from '../../../contracts/types/source-sync';
import { SourceIndex } from './SourceIndex';

const stages = { QUEUED: '排队中', ACQUIRING: '获取文件', PARSING: '解析句子与关系', STORING: '保存结果', VALIDATED: '已校验', FAILED: '失败', CANCELLED: '已取消' };
const states = { QUEUED: '排队中', RUNNING: '运行中', SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消' };
const qualityLabels: Record<string, string> = { cmn_sentences: '中文句子', eng_sentences: '英文句子', direct_edges: '直接中英关系', missing_endpoint_rows: '缺少端点的关系行', wrong_language_edge_rows: '语言不符的关系行', duplicate_sentence_rows: '重复句子行', duplicate_or_reciprocal_edge_rows: '重复或反向关系行', unlinked_sentences: '未配对句子', unknown_owner: '归属人未知' };
const diffLabels: Record<string, string> = { sentence_added: '新增句子', sentence_removed: '移除句子', sentence_changed: '变更句子', sentence_text_changed: '正文变更句子', text_changed: '正文变更句子', edge_added: '新增关系', edge_removed: '移除关系' };
const count = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : '未知';

/** Platform tasks remain separate from project uploads and public releases. */
export function SourceSync({ client, onUnauthorized }: { client: CorpusApiClient; onUnauthorized: (cause: unknown) => void }) {
  const [listing, setListing] = useState<SyncRunList>();
  const [run, setRun] = useState<SyncRunView>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [readError, setReadError] = useState('');
  const cursor = useRef<string | undefined>(undefined);
  const selected = useRef<string | undefined>(undefined);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  const mutation = useRef(false);
  const mounted = useRef(true);
  const key = useRef<{ operation: string; value: string } | undefined>(undefined);
  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) onUnauthorized(cause);
    const messages: Record<string, string> = { ADMIN_REQUIRED: '需要平台管理员权限。', SYNC_ALREADY_ACTIVE: '已有同步任务，请读取当前状态。', CONNECTOR_UNAVAILABLE: '来源尚未配置同步。', SOURCE_IDENTITY_CHANGED: '来源身份已变更，固定连接器不能用于此登记。', SYNC_NOT_RETRYABLE: '该任务不能重试。', SYNC_RUN_NOT_FOUND: '同步任务不存在。', SYNC_ACTOR_REVOKED: '原发起人已失去权限，请创建新任务。', IDEMPOTENCY_CONFLICT: '提交标识与原参数不一致。' };
    return cause instanceof ApiError ? messages[cause.code] || cause.message : '读取或提交失败，请重试。';
  }
  async function refresh(background = false) {
    if (background && (inFlight.current || mutation.current)) return;
    const request = ++sequence.current; inFlight.current = true;
    if (!background) { setLoading(true); setError(''); }
    try {
      const value = await client.syncRuns('D12', cursor.current, 10);
      const chosen = value.items.find(item => item.id === selected.current) ?? value.items[0];
      if (!mounted.current || request !== sequence.current) return;
      selected.current = chosen?.id; setListing(value); setRun(chosen); setReadError('');
    } catch (cause) { if (mounted.current && request === sequence.current) setReadError(fail(cause)); }
    finally { if (request === sequence.current) { inFlight.current = false; if (mounted.current) setLoading(false); } }
  }
  useEffect(() => {
    mounted.current = true; void refresh();
    const interval = setInterval(() => void refresh(true), 3000);
    return () => { mounted.current = false; sequence.current++; clearInterval(interval); };
  }, []);
  async function act(operation: 'start' | 'cancel' | 'retry') {
    if (mutation.current || (operation !== 'start' && !run)) return;
    const operationId = `${operation}:${operation === 'start' ? 'D12' : run!.id}`;
    if (key.current?.operation !== operationId) key.current = { operation: operationId, value: crypto.randomUUID() };
    mutation.current = true; setSaving(true); setError(''); sequence.current++;
    try {
      const result = operation === 'start' ? await client.startSync('D12', key.current.value)
        : operation === 'cancel' ? await client.cancelSync(run!.id, key.current.value) : await client.retrySync(run!.id, key.current.value);
      if (!mounted.current) return;
      key.current = undefined; cursor.current = undefined; selected.current = result.sync_run_id; setRun(result.run);
      await refresh();
    } catch (cause) { if (mounted.current) setError(fail(cause)); }
    finally { mutation.current = false; inFlight.current = false; if (mounted.current) setSaving(false); }
  }
  const quality = run?.result?.quality;
  const diff = run?.result?.diff;
  return <section className="source-sync">
    <div className="section-title"><h2>Tatoeba 同步</h2><button disabled={saving || loading || !listing?.allowed_actions.start} onClick={() => void act('start')}>{saving ? '提交中…' : '同步'}</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {readError && <p className="error" role="alert">{readError}</p>}
    <button disabled={saving || loading} onClick={() => void refresh()}>重新读取</button>
    {loading && <p role="status">正在读取同步任务…</p>}
    {listing && <><p>共 {listing.total} 次同步</p>{!listing.items.length ? <p>暂无同步任务</p> : <ul className="source-list">{listing.items.map(item => <li key={item.id}><button disabled={saving} aria-pressed={run?.id === item.id} onClick={() => { selected.current = item.id; setRun(item); }}><strong>{new Date(item.created_at).toLocaleString()} · {states[item.state]}</strong><span>{stages[item.stage]} · 第 {item.attempt} 次尝试</span></button></li>)}</ul>}
      <div className="actions">{cursor.current && <button disabled={saving || loading} onClick={() => { cursor.current = undefined; selected.current = undefined; void refresh(); }}>返回最新任务</button>}{listing.next_cursor && <button disabled={saving || loading} onClick={() => { cursor.current = listing.next_cursor!; selected.current = undefined; void refresh(); }}>更早任务</button>}</div></>}
    {run && <div className="sync-result"><h3>同步详情</h3><dl>
      <div><dt>状态</dt><dd>{states[run.state]} · {stages[run.stage]}</dd></div>
      {run.state !== 'SUCCEEDED' && <><div><dt>文件</dt><dd>{run.progress.file_name || '无当前文件'}</dd></div>
      <div><dt>文件字节</dt><dd>{count(run.progress.processed_bytes)} / {count(run.progress.total_bytes)}</dd></div>
      <div><dt>处理记录</dt><dd>{count(run.progress.processed_records)} / {count(run.progress.total_records)}</dd></div></>}
      <div><dt>尝试次数</dt><dd>{run.attempt}</dd></div>
    </dl>{run.error && <p className="error" role="alert">{run.error.code}：{run.error.message}</p>}
    <div className="actions">{run.allowed_actions.cancel && <button disabled={saving} onClick={() => void act('cancel')}>取消同步</button>}{run.allowed_actions.retry && <button disabled={saving} onClick={() => void act('retry')}>重试同步</button>}</div>
    {run.result && <><h3>已校验暂存版本</h3><dl><div><dt>检索状态</dt><dd>暂存数据不可直接检索</dd></div><div><dt>上游导出日期</dt><dd>{run.result.export_date || '未知'}</dd></div><div><dt>许可声明</dt><dd>{typeof run.result.license.declared === 'string' ? run.result.license.declared : '未知'}</dd></div><div><dt>模型外发</dt><dd>未批准</dd></div></dl>
      <h3>质量结果</h3><dl>{Object.entries(qualityLabels).filter(([field]) => quality && field in quality).map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{count(quality![field])}</dd></div>)}</dl>
      <h3>与前版比较</h3>{diff?.status === 'initial' ? <p>首次同步，无前版</p> : <p>按上游句子 ID 与直接关系比较</p>}<dl>{Object.entries(diffLabels).filter(([field]) => diff && field in diff).map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{count(diff![field])}</dd></div>)}</dl>
      <details><summary>版本记录</summary><p className="digest">{run.result.acquisition_id}</p><p className="digest">{run.result.manifest_sha256}</p></details></>}
    <details><summary>任务记录</summary><p className="digest">{run.id}</p><p>来源登记修订 {run.source_revision} · {new Date(run.updated_at).toLocaleString()}</p></details></div>}
    <SourceIndex client={client} acquisitionId={run?.result?.acquisition_id} onUnauthorized={onUnauthorized} />
  </section>;
}
