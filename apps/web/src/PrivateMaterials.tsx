import { useEffect, useRef, useState } from 'react';
import { ApiError, type CorpusApiClient } from '../../../contracts/types/s1';
import type { ImportList, ImportView, MaterialList, ValidatedUploadList } from '../../../contracts/types/materials';

const states: Record<string, string> = { QUEUED: '排队中', RUNNING: '解析中', SUCCEEDED: '解析完成', FAILED: '失败', CANCELLED: '已取消', IMPORTING: '解析中', READY: '可选入快照', FETCHING: '读取原件', PARSING: '解析文本', STORING: '保存修订', COMPLETE: '完成' };
const languageNames = { cmn: '中文', eng: '英文' };
export function PrivateMaterials({ client, projectId, canWrite, refreshToken, onUnauthorized }: { client: CorpusApiClient; projectId: string; canWrite: boolean; refreshToken: string; onUnauthorized: (error: unknown) => void }) {
  const [uploads, setUploads] = useState<ValidatedUploadList>();
  const [imports, setImports] = useState<ImportList>();
  const [materials, setMaterials] = useState<MaterialList>();
  const [selected, setSelected] = useState<ImportView>();
  const [uploadId, setUploadId] = useState('');
  const [language, setLanguage] = useState<'' | 'cmn' | 'eng'>('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true); const listSequence = useRef(0); const runSequence = useRef(0); const selectedId = useRef<string | undefined>(undefined);
  const previousState = useRef<string | undefined>(undefined);
  const keys = useRef(new Map<string, string>());
  function key(name: string) { let value = keys.current.get(name); if (!value) { value = crypto.randomUUID(); keys.current.set(name, value); } return value; }
  function fail(cause: unknown) {
    if (!alive.current) return;
    setError(cause instanceof Error ? cause.message : '读取失败，请重试');
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { listSequence.current++; runSequence.current++; setUploads(undefined); setImports(undefined); setMaterials(undefined); setSelected(undefined); setUploadId(''); selectedId.current = undefined; if (cause.status === 401) onUnauthorized(cause); }
  }
  async function load(uploadCursor?: string, importCursor?: string, materialCursor?: string) {
    const sequence = ++listSequence.current;
    try {
      const [u, i, m] = await Promise.all([client.validatedUploads(projectId, uploadCursor), client.imports(projectId, importCursor), client.materials(projectId, materialCursor)]);
      if (!alive.current || sequence !== listSequence.current) return;
      setUploads(u); setUploadId(previous => u.items.some(item => item.upload_id === previous) ? previous : ''); setImports(i); setMaterials(m); setError(''); if (!selectedId.current && i.items.length) { selectedId.current = i.items[0].id; previousState.current = i.items[0].state; setSelected(i.items[0]); }
    } catch (cause) { if (sequence === listSequence.current) fail(cause); }
  }
  async function read(id: string) {
    const sequence = ++runSequence.current;
    try { const value = await client.import(projectId, id); if (!alive.current || selectedId.current !== id || sequence !== runSequence.current) return; const changedToTerminal = previousState.current !== value.state && ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(value.state); previousState.current = value.state; setSelected(value); if (changedToTerminal) void load(); }
    catch (cause) { if (sequence === runSequence.current) fail(cause); }
  }
  useEffect(() => { alive.current = true; void load(); let timer: ReturnType<typeof setTimeout>; async function poll() { if (selectedId.current) await read(selectedId.current); if (alive.current) timer = setTimeout(() => void poll(), 2500); } timer = setTimeout(() => void poll(), 2500); return () => { alive.current = false; listSequence.current++; runSequence.current++; clearTimeout(timer); }; }, [projectId]);
  useEffect(() => { void load(); }, [refreshToken]);
  async function start() {
    if (!uploadId || !language) return; setBusy(true); setError('');
    try { const value = await client.startImport(projectId, { upload_id: uploadId, language }, key(`import:${uploadId}:${language}`)); if (!alive.current) return; selectedId.current = value.import_id; setSelected(value.run); await load(); }
    catch (cause) { fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function control(action: 'cancel' | 'retry') {
    if (!selected) return; setBusy(true); const id = selected.id;
    try { await (action === 'cancel' ? client.cancelJob(selected.job_id, key(`${action}:${id}:${selected.attempt}`)) : client.retryJob(selected.job_id, key(`${action}:${id}:${selected.attempt}`))); if (selectedId.current === id) await read(id); }
    catch (cause) { fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  return <section className="private-materials">
    <div className="section-title"><h2>私有文本</h2><button disabled={busy} onClick={() => { void load(); if (selectedId.current) void read(selectedId.current); }}>刷新材料</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {canWrite && <div className="form-grid"><label>已校验 TXT<select value={uploadId} onChange={event => setUploadId(event.target.value)}><option value="">选择文件</option>{uploads?.items.filter(item => ['text/plain', 'application/octet-stream'].includes(item.media_type) && /\.txt$/i.test(item.filename)).map(item => <option key={item.upload_id} value={item.upload_id}>{item.filename} · {item.size.toLocaleString()} B</option>)}</select></label><label>文本语言<select value={language} onChange={event => setLanguage(event.target.value as typeof language)}><option value="">选择语言</option><option value="cmn">中文</option><option value="eng">英文</option></select></label><button disabled={busy || !uploadId || !language} onClick={() => void start()}>解析 TXT</button></div>}
    {canWrite && <div className="actions"><button disabled={busy} onClick={() => { setUploadId(''); void load(); }}>返回首批文件</button>{uploads?.next_cursor && <button disabled={busy} onClick={() => { setUploadId(''); void load(uploads.next_cursor!); }}>更多已校验文件</button>}</div>}
    <h3>固定材料修订</h3>{materials && !materials.items.length ? <p>暂无已解析材料</p> : <ul className="source-list">{materials?.items.map(item => <li key={item.id}><strong>{item.name}</strong><span>{states[item.state]}</span>{item.revisions.map(revision => <p key={revision.id}>修订 {revision.revision} · {languageNames[revision.language]} · {revision.counts.documents} 文件 / {revision.counts.segments.toLocaleString()} 句段 / {revision.counts.characters.toLocaleString()} 码点</p>)}</li>)}</ul>}
    {materials?.next_cursor && <button onClick={() => void load(undefined, undefined, materials.next_cursor!)}>更多材料</button>}
    <details open><summary>解析任务</summary>{imports && !imports.items.length ? <p>暂无解析任务</p> : <ul className="source-list">{imports?.items.map(item => <li key={item.id}><button onClick={() => { selectedId.current = item.id; setSelected(undefined); void read(item.id); }}>{item.filename} · {languageNames[item.language]} · {states[item.state]}</button></li>)}</ul>}{imports?.next_cursor && <button onClick={() => void load(undefined, imports.next_cursor!)}>更多解析任务</button>}</details>
    {selected && <section className="detail"><h3>{selected.filename}</h3><dl><div><dt>状态</dt><dd>{states[selected.state]} · {states[selected.stage]}</dd></div><div><dt>执行次数</dt><dd>{selected.attempt}</dd></div>{selected.state !== 'SUCCEEDED' && <div><dt>已处理</dt><dd>{selected.progress.processed_bytes.toLocaleString()} B / {selected.progress.total_bytes?.toLocaleString() ?? '未知'} B · {selected.progress.processed_records.toLocaleString()} 条</dd></div>}</dl>{selected.error && <p role="alert">{selected.error.message}</p>}{selected.result && <><p>修订 {selected.result.revision} 已保存，可在语料检索中选择建立快照。</p><dl><div><dt>文件 / 句段 / 码点</dt><dd>{selected.result.counts.documents} / {selected.result.counts.segments.toLocaleString()} / {selected.result.counts.characters.toLocaleString()}</dd></div><div><dt>原文保留 / 拒绝句段</dt><dd>{selected.result.quality.complete_text_preserved ? '完整保留' : '未完整保留'} / {selected.result.quality.rejected_segments}</dd></div><div><dt>分句方式</dt><dd>固定标点与换行规则</dd></div><div><dt>正文摘要</dt><dd className="digest">{selected.result.canonical_sha256}</dd></div></dl></>}<div className="actions">{selected.allowed_actions.cancel && <button disabled={busy} onClick={() => void control('cancel')}>取消解析</button>}{selected.allowed_actions.retry && <button disabled={busy} onClick={() => void control('retry')}>重试解析</button>}</div></section>}
  </section>;
}
