import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, type CorpusApiClient } from '../../../contracts/types/s1';
import type { EvidenceList, EvidenceView, ExportList, ExportView, NoteInput, NoteList, NoteView } from '../../../contracts/types/outcomes';
import type { QueryList } from '../../../contracts/types/research';

const states: Record<string, string> = { QUEUED: '排队中', RUNNING: '处理中', SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消', EXPORTING: '生成成果', STORING: '保存成果', COMPLETE: '已完成' };
const emptyDraft = (): NoteInput => ({ title: '', body: '', evidence_ids: [], query_run_ids: [] });

export function Outcomes({ client, projectId, initialExportId, leaveGuard, onUnauthorized }: { client: CorpusApiClient; projectId: string; initialExportId?: string; leaveGuard: { current: (() => boolean) | undefined }; onUnauthorized: (cause: unknown) => void }) {
  const [tab, setTab] = useState<'notes' | 'evidence' | 'exports'>(initialExportId ? 'exports' : 'notes');
  const [notes, setNotes] = useState<NoteList>(); const [evidence, setEvidence] = useState<EvidenceList>(); const [queries, setQueries] = useState<QueryList>();
  const [exports, setExports] = useState<ExportList>(); const [note, setNote] = useState<NoteView>(); const [revisions, setRevisions] = useState<NoteList>();
  const [proof, setProof] = useState<EvidenceView>(); const [exportRun, setExportRun] = useState<ExportView>();
  const [draft, setDraft] = useState<NoteInput>(emptyDraft); const [editing, setEditing] = useState(false); const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const listCursor = useRef<string | undefined>(undefined); const generation = useRef(0); const proofSeq = useRef(0); const choicesSeq = useRef(0);
  const alive = useRef(true); const readSeq = useRef(0); const detailSeq = useRef(0); const exportSeq = useRef(0);
  const selected = useRef<{ note?: string; revision?: number; proof?: string; export?: string }>({ export: initialExportId });
  const draftRevision = useRef<number | undefined>(undefined); const dirtyRef = useRef(false); const keys = useRef(new Map<string, string>());
  function mutationKey(operation: string) { const previous = keys.current.get(operation); if (previous) return previous; const value = crypto.randomUUID(); keys.current.set(operation, value); return value; }
  function clearSensitive() { generation.current++; readSeq.current++; exportSeq.current++; proofSeq.current++; choicesSeq.current++; detailSeq.current++; selected.current = {}; draftRevision.current = undefined; setNote(undefined); setProof(undefined); setRevisions(undefined); setNotes(undefined); setEvidence(undefined); setQueries(undefined); setDraft(emptyDraft()); setEditing(false); setDirty(false); dirtyRef.current = false; }
  function fail(cause: unknown) { if (!alive.current) return; if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { clearSensitive(); setExportRun(undefined); setExports(undefined); if (cause.status === 401) onUnauthorized(cause); } setError(cause instanceof Error ? cause.message : '读取失败，请重试。'); }
  async function read(cursor?: string, kind = tab) {
    listCursor.current = cursor; const epoch = generation.current; const seq = ++readSeq.current;
    try {
    const value = kind === 'notes' ? await client.notes(projectId, cursor) : kind === 'evidence' ? await client.evidenceList(projectId, cursor) : await client.exports(projectId, cursor);
    if (!alive.current || seq !== readSeq.current || epoch !== generation.current) return;
    if (kind === 'notes') setNotes(value as NoteList); else if (kind === 'evidence') setEvidence(value as EvidenceList); else setExports(value as ExportList);
    } catch (cause) { if (epoch === generation.current && seq === readSeq.current) fail(cause); }
  }
  async function choices(evidenceCursor?: string, queryCursor?: string) {
    const epoch = generation.current; const seq = ++choicesSeq.current;
    try {
    const [e, q] = await Promise.all([client.evidenceList(projectId, evidenceCursor), client.queries(projectId, queryCursor)]);
    if (alive.current && epoch === generation.current && seq === choicesSeq.current) { setEvidence(e); setQueries(q); }
    } catch (cause) { if (epoch === generation.current && seq === choicesSeq.current) fail(cause); }
  }
  function allowLeave() { return !dirtyRef.current || window.confirm('尚有未保存修改，放弃这些修改？'); }
  function changeTab(value: typeof tab) { if (value === tab || !allowLeave()) return; generation.current++; selected.current = {}; setNote(undefined); setProof(undefined); setExportRun(undefined); setRevisions(undefined); setEditing(false); setDraft(emptyDraft()); setDirty(false); dirtyRef.current = false; setTab(value); setError(''); setNotice(''); }
  async function openNote(id: string, revision?: number, poll = false) {
    if (!poll && !allowLeave()) return;
    if (!poll) { selected.current.note = id; selected.current.revision = revision; selected.current.proof = undefined; proofSeq.current++; setNote(undefined); setProof(undefined); setEditing(false); setDirty(false); dirtyRef.current = false; }
    const epoch = generation.current; const seq = ++detailSeq.current;
    try {
      const value = await client.note(projectId, id, revision);
      if (!alive.current || seq !== detailSeq.current || epoch !== generation.current || selected.current.note !== id || selected.current.revision !== revision) return;
      setNote(value);
      if (!poll) { const history = await client.noteRevisions(projectId, id); if (alive.current && epoch === generation.current && seq === detailSeq.current) setRevisions(history); }
    } catch (cause) { if (seq === detailSeq.current) fail(cause); }
  }
  async function openEvidence(id: string, poll = false) {
    selected.current.proof = id; if (!poll) setProof(undefined); const epoch = generation.current; const seq = ++proofSeq.current;
    try { const value = await client.evidence(projectId, id); if (alive.current && seq === proofSeq.current && epoch === generation.current && selected.current.proof === id) setProof(value); }
    catch (cause) { if (epoch === generation.current && seq === proofSeq.current) fail(cause); }
  }
  async function openExport(id: string) {
    selected.current.export = id; const epoch = generation.current; const seq = ++exportSeq.current;
    try { const value = await client.export(projectId, id); if (alive.current && seq === exportSeq.current && epoch === generation.current && selected.current.export === id) setExportRun(value); }
    catch (cause) { if (epoch === generation.current && seq === exportSeq.current) fail(cause); }
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; readSeq.current++; detailSeq.current++; exportSeq.current++; }; }, []);
  useEffect(() => { leaveGuard.current = allowLeave; return () => { leaveGuard.current = undefined; }; }, [leaveGuard]);
  useEffect(() => { void read(undefined, tab).catch(fail); }, [tab]);
  useEffect(() => { if (initialExportId) void openExport(initialExportId); }, [initialExportId]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (busy) return;
      void read(listCursor.current, tab).catch(fail);
      if (tab === 'notes' && selected.current.note) void openNote(selected.current.note, selected.current.revision, true);
      if (tab !== 'exports' && selected.current.proof) void openEvidence(selected.current.proof, true);
      if (tab === 'exports' && selected.current.export) void openExport(selected.current.export);
    }, 2500); return () => window.clearInterval(timer);
  }, [tab, busy]);
  useEffect(() => { const guard = (event: BeforeUnloadEvent) => { if (dirtyRef.current) event.preventDefault(); }; window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard); }, []);
  async function edit(create = false) {
    if (!allowLeave()) return;
    if (create) { detailSeq.current++; proofSeq.current++; selected.current.note = undefined; selected.current.revision = undefined; selected.current.proof = undefined; setProof(undefined); setNote(undefined); setRevisions(undefined); draftRevision.current = undefined; setDraft(emptyDraft()); }
    else if (note) { draftRevision.current = note.revision; setDraft({ title: note.title, body: note.body, evidence_ids: [...note.evidence_ids], query_run_ids: [...note.query_run_ids] }); }
    setEditing(true); setDirty(false); dirtyRef.current = false; setNotice(''); await choices().catch(fail);
  }
  function updateDraft(value: Partial<NoteInput>) { setDraft(current => ({ ...current, ...value })); setDirty(true); dirtyRef.current = true; }
  function toggle(kind: 'evidence_ids' | 'query_run_ids', id: string) { updateDraft({ [kind]: draft[kind].includes(id) ? draft[kind].filter(value => value !== id) : [...draft[kind], id] }); }
  async function save(event: FormEvent) {
    event.preventDefault(); const epoch = generation.current; setBusy(true); setError(''); const id = selected.current.note; const operation = JSON.stringify(['note', id, draftRevision.current, draft]);
    try {
      const value = id && draftRevision.current ? await client.updateNote(projectId, id, { ...draft, expected_revision: draftRevision.current }, mutationKey(operation)) : await client.createNote(projectId, draft, mutationKey(operation));
      if (!alive.current || epoch !== generation.current) return; keys.current.delete(operation); setDirty(false); dirtyRef.current = false; setEditing(false); setNotice('已保存新修订'); await read(undefined, 'notes'); await openNote(value.note.id);
    } catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function accept() {
    if (!note) return; const epoch = generation.current; const current = note; setBusy(true); setError(''); const operation = `accept:${current.id}:${current.revision}`;
    try { const value = await client.acceptNote(projectId, current.id, current.revision, mutationKey(operation)); if (alive.current && epoch === generation.current) { keys.current.delete(operation); setNote(value.note); setRevisions(history => history ? { ...history, items: history.items.map(item => item.revision === value.note.revision ? { ...item, status: value.note.status, accepted_by: value.note.accepted_by, accepted_at: value.note.accepted_at, allowed_actions: value.note.allowed_actions } : item) } : history); setNotice(`已接受修订 ${value.note.revision}`); await read(undefined, 'notes'); } }
    catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function exportNote(format: 'csv' | 'json') {
    if (!note) return; const epoch = generation.current; const current = note; setBusy(true); setError(''); const operation = `export:${current.id}:${current.revision}:${format}`;
    try { const value = await client.createExport(projectId, { target: { kind: 'note_revision', note_id: current.id, revision: current.revision }, format }, mutationKey(operation)); if (alive.current && epoch === generation.current) { keys.current.delete(operation); setExportRun(value.run); selected.current.export = value.export_id; setTab('exports'); } }
    catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function exportAction(action: 'cancel' | 'retry' | 'download') {
    if (!exportRun) return; const epoch = generation.current; const current = exportRun; setBusy(true); setError('');
    try {
      if (action === 'download') { const blob = await client.downloadExport(projectId, current.id); if (!alive.current || epoch !== generation.current) return; const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = current.result?.filename || 'export'; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
      else { const k = mutationKey(`${action}:${current.id}:${current.attempt}`); if (action === 'cancel') await client.cancelJob(current.job_id, k); else await client.retryJob(current.job_id, k); if (!alive.current || epoch !== generation.current) return; await openExport(current.id); await read(undefined, 'exports'); }
    } catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function moreRevisions() {
    if (!note || !revisions?.next_cursor) return; const id = note.id; const epoch = generation.current;
    try { const value = await client.noteRevisions(projectId, id, revisions.next_cursor); if (alive.current && epoch === generation.current && selected.current.note === id) setRevisions(current => current ? { ...value, items: [...current.items, ...value.items] } : value); }
    catch (cause) { if (epoch === generation.current) fail(cause); }
  }
  const listing = tab === 'notes' ? notes : tab === 'evidence' ? evidence : exports;
  return <section className="outcomes"><nav className="actions" aria-label="研究成果"><button className={tab === 'notes' ? 'selected' : ''} onClick={() => changeTab('notes')}>研究笔记</button><button className={tab === 'evidence' ? 'selected' : ''} onClick={() => changeTab('evidence')}>已保存证据</button><button className={tab === 'exports' ? 'selected' : ''} onClick={() => changeTab('exports')}>导出任务</button><button disabled={busy} onClick={() => void read().catch(fail)}>刷新列表</button></nav>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {tab === 'notes' && <><div className="section-title"><h2>研究笔记</h2>{notes?.allowed_actions.create && <button disabled={busy} onClick={() => void edit(true)}>新建笔记</button>}</div>{notes?.items.length === 0 && <p>暂无笔记</p>}<ul className="source-list">{notes?.items.map(item => <li key={item.id}><button disabled={busy} onClick={() => void openNote(item.id)}>{item.title} · 修订 {item.revision} · {item.status === 'accepted' ? '已接受' : '草稿'}</button></li>)}</ul>
      {editing ? <form onSubmit={event => void save(event)}><label>标题<input required maxLength={160} disabled={busy} value={draft.title} onChange={event => updateDraft({ title: event.target.value })}/></label><label>正文<textarea className="note-body" required maxLength={100000} disabled={busy} value={draft.body} onChange={event => updateDraft({ body: event.target.value })}/></label>
        <fieldset><legend>关联证据</legend>{evidence?.items.map(item => <label className="check-row" key={item.id}><input type="checkbox" checked={draft.evidence_ids.includes(item.id)} disabled={busy} onChange={() => toggle('evidence_ids', item.id)}/>命中 {item.hit_ref.ordinal + 1} · {item.id}</label>)}{evidence?.next_cursor && <button type="button" onClick={() => void choices(evidence.next_cursor!).catch(fail)}>查看更多证据</button>}</fieldset>
        <fieldset><legend>关联完整查询</legend>{queries?.items.filter(item => item.count_state === 'complete').map(item => <label className="check-row" key={item.id}><input type="checkbox" checked={draft.query_run_ids.includes(item.id)} disabled={busy} onChange={() => toggle('query_run_ids', item.id)}/>{item.name}</label>)}{queries?.next_cursor && <button type="button" onClick={() => void choices(undefined, queries.next_cursor!).catch(fail)}>查看更多查询</button>}</fieldset>
        {(draft.evidence_ids.length > 0 || draft.query_run_ids.length > 0) && <details><summary>已选引用（{draft.evidence_ids.length + draft.query_run_ids.length}）</summary>{(['evidence_ids', 'query_run_ids'] as const).flatMap(kind => draft[kind].map(id => <p className="digest" key={`${kind}:${id}`}>{kind === 'evidence_ids' ? '证据' : '查询'} {id} <button type="button" onClick={() => toggle(kind, id)}>移除</button></p>))}</details>}
        <div className="actions"><button type="submit" disabled={busy}>保存笔记</button><button type="button" disabled={busy} onClick={() => { if (allowLeave()) { setEditing(false); setDirty(false); dirtyRef.current = false; } }}>取消编辑</button></div>{dirty && <p>尚未保存</p>}{error && <button type="button" onClick={() => { if (selected.current.note) void openNote(selected.current.note); }}>重新读取服务器修订</button>}</form> : note && <section className="detail"><h3>{note.title}</h3><p>修订 {note.revision} · {note.status === 'accepted' ? '已接受' : '草稿'}</p><p className="sentence-text">{note.body}</p><div className="actions">{note.allowed_actions.update && <button disabled={busy} onClick={() => void edit()}>编辑新修订</button>}{note.allowed_actions.accept && <button disabled={busy} onClick={() => void accept()}>接受此修订</button>}{note.allowed_actions.export && <><button disabled={busy} onClick={() => void exportNote('csv')}>导出 CSV 成果包</button><button disabled={busy} onClick={() => void exportNote('json')}>导出 JSON</button></>}</div><details><summary>修订与材料范围</summary><label>读取修订<select value={note.revision} onChange={event => void openNote(note.id, Number(event.target.value))}>{revisions?.items.map(item => <option key={item.revision} value={item.revision}>修订 {item.revision} · {item.status === 'accepted' ? '已接受' : '草稿'}</option>)}</select></label>{revisions?.next_cursor && <button onClick={() => void moreRevisions()}>查看更多修订</button>}{note.evidence_ids.map(id => <p key={id}><button onClick={() => void openEvidence(id)}>读取证据 {id}</button></p>)}<p>授权依赖保留 {note.authorization_evidence_ids.length} 份证据与 {note.authorization_query_run_ids.length} 个查询，移除展示引用不解除该范围。</p>{note.accepted_at && <p>接受时间：{new Date(note.accepted_at).toLocaleString()}</p>}</details></section>}
    </>}
    {tab === 'evidence' && <><h2>已保存证据</h2>{evidence?.items.length === 0 && <p>暂无已保存证据</p>}<ul className="source-list">{evidence?.items.map(item => <li key={item.id}><button disabled={busy} onClick={() => void openEvidence(item.id)}>命中 {item.hit_ref.ordinal + 1} · {new Date(item.created_at).toLocaleString()}</button></li>)}</ul></>}
    {tab !== 'exports' && proof && <section className="detail"><h3>证据原句</h3><p className="sentence-text">{Array.from(proof.context.text).slice(0, proof.context.start_cp - proof.context.context_start_cp).join('')}<mark>{Array.from(proof.context.text).slice(proof.context.start_cp - proof.context.context_start_cp, proof.context.end_cp - proof.context.context_start_cp).join('')}</mark>{Array.from(proof.context.text).slice(proof.context.end_cp - proof.context.context_start_cp).join('')}</p><p>全文码点 [{proof.context.start_cp}, {proof.context.end_cp})</p><details><summary>证据记录</summary><p className="digest">{proof.id}</p><p className="digest">{proof.snapshot_id}</p></details></section>}
    {tab === 'exports' && <><h2>导出任务</h2>{exports?.items.length === 0 && <p>暂无导出任务</p>}<ul className="source-list">{exports?.items.map(item => <li key={item.id}><button disabled={busy} onClick={() => void openExport(item.id)}>{item.format === 'csv' ? 'CSV 成果包' : 'JSON'} · {states[item.state]} · {new Date(item.created_at).toLocaleString()}</button></li>)}</ul>{exportRun && <section className="detail"><h3>{exportRun.format === 'csv' ? 'CSV 成果包' : 'JSON'}</h3><p>{states[exportRun.stage]} · 尝试 {exportRun.attempt}</p>{exportRun.state !== 'SUCCEEDED' && <p>已处理 {exportRun.progress.processed_records.toLocaleString()} 条{exportRun.progress.total_records !== null ? ` / ${exportRun.progress.total_records.toLocaleString()}` : ''}</p>}{exportRun.error && <p className="error" role="alert">{exportRun.error.message}</p>}{exportRun.result && <dl><div><dt>文件</dt><dd>{exportRun.result.filename}</dd></div><div><dt>记录数</dt><dd>{exportRun.result.row_count.toLocaleString()}</dd></div><div><dt>字节数</dt><dd>{exportRun.result.byte_size.toLocaleString()}</dd></div><div><dt>SHA-256</dt><dd className="digest">{exportRun.result.sha256}</dd></div></dl>}<div className="actions">{exportRun.allowed_actions.cancel && <button disabled={busy} onClick={() => void exportAction('cancel')}>取消导出</button>}{exportRun.allowed_actions.retry && <button disabled={busy} onClick={() => void exportAction('retry')}>重试导出</button>}{exportRun.allowed_actions.download && <button disabled={busy} onClick={() => void exportAction('download')}>下载成果</button>}</div><details><summary>导出范围与编码</summary><p>{exportRun.target.kind === 'query_runs' ? `${exportRun.target.query_run_ids.length} 个固定查询的全部命中` : `固定笔记修订 ${exportRun.target.revision}`}</p>{exportRun.format === 'csv' && <p>压缩包包含 results.csv 和 methods.json。CSV 非空文本以前置单引号保护公式，去除一个前缀可恢复原文；JSON 导出保留原文。</p>}</details></section>}</>}
    <div className="actions"><button disabled={busy} onClick={() => void read().catch(fail)}>返回首批</button>{listing?.next_cursor && <button disabled={busy} onClick={() => void read(listing.next_cursor!).catch(fail)}>查看更多</button>}</div>
  </section>;
}
