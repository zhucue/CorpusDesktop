import { useEffect, useRef, useState } from 'react';
import { SourcePublication } from './SourcePublication';
import { ApiError, CorpusApiClient } from '../../../contracts/types/s1';
import type { IndexRunList, IndexRunView } from '../../../contracts/types/source-index';

const stages = { QUEUED: '排队中', FETCHING: '读取固定版本', INDEXING: '构建索引', VERIFYING: '校验索引', STORING: '保存索引', INDEXED: '索引已保存', FAILED: '失败', CANCELLED: '已取消' };
const states = { QUEUED: '排队中', RUNNING: '运行中', SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消' };
const count = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : '未知';
const countLabels: Record<string, string> = { sentences: '句子总数', cmn_sentences: '中文句子', eng_sentences: '英文句子', characters: 'Unicode 码点', tokens: '词项（含标点，不含空白）', direct_edges: '有效直接关系', unknown_owner: '归属人未知' };

export function SourceIndex({ client, sourceId = 'D12', acquisitionId, onUnauthorized }: { client: CorpusApiClient; sourceId?: string; acquisitionId?: string; onUnauthorized: (cause: unknown) => void }) {
  const [listing, setListing] = useState<IndexRunList>();
  const [run, setRun] = useState<IndexRunView>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [readError, setReadError] = useState('');
  const [notice, setNotice] = useState('');
  const cursor = useRef<string | undefined>(undefined);
  const selected = useRef<string | undefined>(undefined);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  const mutation = useRef(false);
  const mounted = useRef(true);
  const key = useRef<{ operation: string; value: string } | undefined>(undefined);
  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) onUnauthorized(cause);
    const messages: Record<string, string> = { ADMIN_REQUIRED: '需要平台管理员权限。', INDEX_ALREADY_ACTIVE: '已有索引任务，请读取当前状态。', INDEX_NOT_RETRYABLE: '该索引任务不能重试。', INDEX_RUN_NOT_FOUND: '索引任务不存在。', ACQUISITION_NOT_FOUND: '已校验版本不存在。', SOURCE_IDENTITY_CHANGED: '来源身份已变更，不能构建索引。', IDEMPOTENCY_CONFLICT: '提交标识与原参数不一致。' };
    return cause instanceof ApiError ? messages[cause.code] || cause.message : '读取或提交失败，请重试。';
  }
  async function refresh(background = false) {
    if (background && (inFlight.current || mutation.current)) return;
    const request = ++sequence.current; inFlight.current = true;
    if (!background) setLoading(true);
    try {
      const value = await client.indexRuns(sourceId, cursor.current, 10);
      // A reused successful build can be older than the current list page.
      const chosen = value.items.find(item => item.id === selected.current)
        ?? (selected.current ? await client.indexRun(selected.current) : value.items[0]);
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
    if (mutation.current || (operation === 'start' ? !acquisitionId : !run)) return;
    const target = operation === 'start' ? acquisitionId! : run!.id;
    const operationId = `${operation}:${target}`;
    if (key.current?.operation !== operationId) key.current = { operation: operationId, value: crypto.randomUUID() };
    mutation.current = true; setSaving(true); setError(''); setNotice(''); sequence.current++;
    try {
      const result = operation === 'start' ? await client.buildIndex('D12', target, key.current.value)
        : operation === 'cancel' ? await client.cancelIndex(target, key.current.value) : await client.retryIndex(target, key.current.value);
      if (!mounted.current) return;
      key.current = undefined; cursor.current = undefined; selected.current = result.index_run_id; setRun(result.run);
      if (result.existing) setNotice('已找到该版本与处理配置的索引，读取原任务。');
      await refresh();
    } catch (cause) { if (mounted.current) setError(fail(cause)); }
    finally { mutation.current = false; inFlight.current = false; if (mounted.current) setSaving(false); }
  }
  return <section className="source-sync">
    <div className="section-title"><h2>来源索引</h2>{sourceId === 'D12' && <button disabled={saving || loading || !acquisitionId || !listing?.allowed_actions.start} onClick={() => void act('start')}>{saving ? '提交中…' : '为所选版本建立索引'}</button>}</div>
    {sourceId === 'D12' && (acquisitionId ? <p className="digest">所选已校验版本：{acquisitionId}</p> : <p>选择已完成的同步任务后可建立索引。</p>)}
    {error && <p className="error" role="alert">{error}</p>}{readError && <p className="error" role="alert">{readError}</p>}{notice && <p role="status">{notice}</p>}
    <button disabled={saving || loading} onClick={() => void refresh()}>重新读取索引任务</button>
    {loading && <p role="status">正在读取索引任务…</p>}
    {listing && <><p>共 {listing.total} 次构建</p>{!listing.items.length ? <p>暂无索引任务</p> : <ul className="source-list">{listing.items.map(item => <li key={item.id}><button disabled={saving} aria-pressed={run?.id === item.id} onClick={() => { selected.current = item.id; setRun(item); }}><strong>{new Date(item.created_at).toLocaleString()} · {states[item.state]}</strong><span>{stages[item.stage]} · 第 {item.attempt} 次尝试</span></button></li>)}</ul>}
      <div className="actions">{cursor.current && <button disabled={saving || loading} onClick={() => { cursor.current = undefined; selected.current = undefined; void refresh(); }}>返回最新构建</button>}{listing.next_cursor && <button disabled={saving || loading} onClick={() => { cursor.current = listing.next_cursor!; selected.current = undefined; void refresh(); }}>更早构建</button>}</div></>}
    {run && <div className="sync-result"><h3>索引详情</h3><dl>
      <div><dt>状态</dt><dd>{states[run.state]} · {stages[run.stage]}</dd></div>
      <div><dt>索引输入版本</dt><dd className="digest">{run.acquisition_id}</dd></div>
      <div><dt>处理配置</dt><dd>{run.recipe.id}</dd></div><div><dt>尝试次数</dt><dd>{run.attempt}</dd></div>
      {run.state !== 'SUCCEEDED' && <><div><dt>文件</dt><dd>{run.progress.file_name || '无当前文件'}</dd></div><div><dt>文件字节</dt><dd>{count(run.progress.processed_bytes)} / {count(run.progress.total_bytes)}</dd></div><div><dt>处理记录</dt><dd>{count(run.progress.processed_records)} / {count(run.progress.total_records)}</dd></div></>}
    </dl>{run.error && <p className="error" role="alert">{run.error.code}：{run.error.message}</p>}
    <div className="actions">{run.allowed_actions.cancel && <button disabled={saving} onClick={() => void act('cancel')}>取消构建</button>}{run.allowed_actions.retry && <button disabled={saving} onClick={() => void act('retry')}>重试构建</button>}</div>
    {run.result && <><h3>私有索引产物</h3><dl><div><dt>检索状态</dt><dd>私有索引已保存，正文检索尚未开放</dd></div><div><dt>产物字节</dt><dd>{count(run.result.artifact_bytes)}</dd></div>{Object.entries(countLabels).map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{count(run.result!.counts[field])}</dd></div>)}</dl>
      <h3>索引校验</h3><dl><div><dt>原句覆盖</dt><dd>{run.result.quality.all_source_sentences_indexed === true ? '全部覆盖' : '未确认全部覆盖'}</dd></div><div><dt>拒绝句子</dt><dd>{count(run.result.quality.rejected_sentences)}</dd></div><div><dt>词项位置回核</dt><dd>{run.result.quality.token_roundtrip_verified === true ? '通过' : '未确认'}</dd></div></dl></>}
    {run.result && <SourcePublication key={run.result.index_id} client={client} sourceId={run.source_id} acquisitionId={run.acquisition_id} indexId={run.result.index_id} onUnauthorized={onUnauthorized}/>}
    <details><summary>索引版本记录</summary><dl><div><dt>配置摘要</dt><dd className="digest">{run.recipe.sha256}</dd></div><div><dt>任务</dt><dd className="digest">{run.id}</dd></div>{run.result && <><div><dt>索引</dt><dd className="digest">{run.result.index_id}</dd></div><div><dt>索引身份摘要</dt><dd className="digest">{run.result.identity_sha256}</dd></div><div><dt>清单摘要</dt><dd className="digest">{run.result.manifest_sha256}</dd></div></>}</dl></details></div>}
  </section>;
}
