import type { MaterialList } from '../../../contracts/types/materials';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, type CorpusApiClient } from '../../../contracts/types/s1';
import type { MountList } from '../../../contracts/types/source-release';
import type { ContextView, GapPattern, HitPage, QueryAST, QueryList, QueryRunView, SnapshotList, SnapshotView } from '../../../contracts/types/research';

const names: Record<string, string> = { PREPARING: '准备中', READY: '已就绪', QUEUED: '排队中', RUNNING: '检索中', SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消', FIRST_PAGE: '读取首屏', FULL_RESULT: '计算完整结果', PREPARING_CACHE: '准备读取', COMPLETE: '已完成' };
const reasons: Record<string, string> = { SOURCE_POLICY_DENIED: '来源许可已受限', SOURCE_POLICY_MISMATCH: '来源许可需要重新核准', SOURCE_IDENTITY_CHANGED: '来源身份已变化', MOUNT_REMOVED: '来源挂载已移除', CACHE_NOT_READY: '结果尚未准备好，请准备读取后重试。' };
function patternSummary(pattern: QueryAST['pattern'] | GapPattern, unit: QueryAST['unit']): string {
  if (pattern.type === 'literal') return JSON.stringify(pattern.value);
  if (pattern.type === 'term') return `词形 ${JSON.stringify(pattern.value)}`;
  if (pattern.type === 'gap') return `间隔 ${pattern.min} 至 ${pattern.max} ${unit === 'character' ? '码点' : '词项'}`;
  if (pattern.type === 'sequence') return pattern.items.map(item => patternSummary(item, unit)).join(' → ');
  return pattern.patterns.map(item => `（${patternSummary(item, unit)}）`).join(' 或 ');
}

export function Research({ client, projectId, canSaveEvidence, onExportCreated, onUnauthorized }: { client: CorpusApiClient; projectId: string; canSaveEvidence: boolean; onExportCreated: (id: string) => void; onUnauthorized: (error: unknown) => void }) {
  const [outcomeNotice, setOutcomeNotice] = useState('');
  const [mounts, setMounts] = useState<MountList>();
  const [snapshots, setSnapshots] = useState<SnapshotList>();
  const [history, setHistory] = useState<QueryList>();
  const [mountIds, setMountIds] = useState<string[]>([]);
  const [revisionIds, setRevisionIds] = useState<string[]>([]);
  const [materials, setMaterials] = useState<MaterialList>();
  const [selectionNames, setSelectionNames] = useState<Record<string, string>>({});
  const [snapshot, setSnapshot] = useState<SnapshotView>();
  const [run, setRun] = useState<QueryRunView>();
  const [page, setPage] = useState<HitPage>();
  const [context, setContext] = useState<ContextView>();
  const [error, setError] = useState('');
  const [pageError, setPageError] = useState('');
  const [cacheMissing, setCacheMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [unit, setUnit] = useState<'character' | 'token'>('character');
  const [mode, setMode] = useState<'single' | 'sequence' | 'gap' | 'any_of'>('single');
  const [text, setText] = useState('');
  const [gapMin, setGapMin] = useState(0);
  const [gapMax, setGapMax] = useState(2);
  const [windowSize, setWindowSize] = useState(40);
  const alive = useRef(true);
  const generation = useRef(0);
  const chosen = useRef<{ snapshot?: string; run?: string; cursor?: string }>({});
  const keys = useRef(new Map<string, string>());
  const listGeneration = useRef(0);
  const runRead = useRef(0);
  const snapshotRead = useRef(0);
  function key(operation: string) { const previous = keys.current.get(operation); if (previous) return previous; const value = crypto.randomUUID(); keys.current.set(operation, value); return value; }
  function clearMaterial() { generation.current++; setPage(undefined); setContext(undefined); setRun(undefined); chosen.current.run = undefined; chosen.current.cursor = undefined; }
  function fail(cause: unknown, material = false) {
    if (!alive.current) return;
    const message = cause instanceof ApiError ? reasons[cause.code] || cause.message : cause instanceof Error ? cause.message : '读取失败，请重试';
    if (material) { setPage(undefined); setContext(undefined); setPageError(message); setCacheMissing(cause instanceof ApiError && cause.code === 'CACHE_NOT_READY'); }
    else setError(message);
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      clearMaterial(); setHistory(undefined); setSnapshot(undefined); setMaterials(undefined); setMounts(undefined); setMountIds([]); setRevisionIds([]); chosen.current.snapshot = undefined;
      if (cause.status === 401) onUnauthorized(cause);
    }
  }
  async function lists(snapshotCursor?: string, historyCursor?: string, mountCursor?: string, materialCursor?: string) {
    const sequence = ++listGeneration.current;
    const [m, s, h, privateMaterials] = await Promise.all([client.mounts(projectId, mountCursor), client.snapshots(projectId, snapshotCursor), client.queries(projectId, historyCursor), client.materials(projectId, materialCursor)]);
    if (!alive.current || sequence !== listGeneration.current) return;
    setMounts(m); setSnapshots(s); setHistory(h); setMaterials(privateMaterials);
  }
  async function readRun(id: string, cursor?: string, epoch = generation.current) {
    const sequence = ++runRead.current;
    const current = () => alive.current && epoch === generation.current && chosen.current.run === id && sequence === runRead.current && chosen.current.cursor === cursor;
    try {
      const value = await client.query(projectId, id);
      if (!current()) return;
      setRun(value);
      if (value.first_page_state !== 'ready') { setPage(undefined); setContext(undefined); return; }
      const hits = await client.hits(projectId, value.result_set_id, cursor);
      if (!current()) return;
      setPage(hits); setPageError(''); setCacheMissing(false);
    } catch (cause) { if (current()) fail(cause, true); }
  }
  async function readSnapshot(id: string, epoch = generation.current) {
    const sequence = ++snapshotRead.current;
    const current = () => alive.current && epoch === generation.current && chosen.current.snapshot === id && sequence === snapshotRead.current;
    try {
      const value = await client.snapshot(projectId, id);
      if (!current()) return;
      setSnapshot(value); setSnapshots(previous => previous ? { ...previous, items: previous.items.map(item => item.id === value.id ? value : item) } : previous);
      if (!value.available && chosen.current.run) clearMaterial();
    } catch (cause) { if (current()) fail(cause); }
  }
  async function selectRun(value: QueryRunView) {
    const epoch = ++generation.current; chosen.current.run = value.id; chosen.current.cursor = undefined; chosen.current.snapshot = value.snapshot_id; setSnapshot(undefined);
    setRun(undefined); setPage(undefined); setContext(undefined); setError(''); setPageError('');
    await readSnapshot(value.snapshot_id, epoch); await readRun(value.id, undefined, epoch);
  }
  async function selectSnapshot(id: string) {
    const epoch = ++generation.current; chosen.current.snapshot = id || undefined; setSnapshot(undefined); setError('');
    // A displayed query always keeps its original snapshot identity.
    setPage(undefined); setContext(undefined); setRun(undefined); chosen.current.run = undefined; chosen.current.cursor = undefined;
    if (!id) return;
    await readSnapshot(id, epoch);
  }
  async function refresh() {
    setError('');
    try {
      await lists();
      if (chosen.current.snapshot) await readSnapshot(chosen.current.snapshot);
      if (chosen.current.run) await readRun(chosen.current.run, chosen.current.cursor);
    } catch (cause) { fail(cause); }
  }
  useEffect(() => {
    alive.current = true; void refresh();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const epoch = generation.current;
      try {
        if (chosen.current.snapshot) {
          await readSnapshot(chosen.current.snapshot, epoch);
        }
        if (chosen.current.run && alive.current && epoch === generation.current) await readRun(chosen.current.run, chosen.current.cursor);
      } catch (cause) { if (epoch === generation.current) fail(cause, true); }
      if (alive.current) timer = setTimeout(() => void poll(), 2500);
    }
    timer = setTimeout(() => void poll(), 2500);
    return () => { alive.current = false; generation.current++; listGeneration.current++; clearTimeout(timer); };
  }, [projectId]);
  async function createSnapshot() {
    if (!mountIds.length && !revisionIds.length) return; setBusy(true); setError('');
    try {
      const value = await client.createSnapshot(projectId, { mount_ids: mountIds, material_revision_ids: revisionIds }, key(`snapshot:${mountIds.join(',')}:${revisionIds.join(',')}`));
      if (!alive.current) return;
      await lists(); await selectSnapshot(value.snapshot.id);
    } catch (cause) { fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function retrySnapshot() {
    if (!snapshot) return; setBusy(true); setError('');
    try { const value = await client.retrySnapshot(projectId, snapshot.id, key(`snapshot-retry:${snapshot.id}:${snapshot.updated_at}`)); if (alive.current && chosen.current.snapshot === snapshot.id) setSnapshot(value.snapshot); }
    catch (cause) { fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  function makeQuery(): QueryAST {
    const values = mode === 'single' ? [text] : text.split(/\r?\n/).filter(value => value.length > 0);
    if (!values.length || (mode !== 'single' && values.length < 2)) throw new Error('请填写查询项；组合查询每行一项，至少两项。');
    if (mode === 'gap' && (values.length !== 2 || gapMin > gapMax)) throw new Error('间隔查询需两项，最小间隔不能大于最大间隔。');
    const base = { dsl_version: 'corpus-query/v1', within: 'sentence', overlap: 'all' } as const;
    function pattern<T extends { type: string }>(atoms: T[]) {
      if (mode === 'single') return atoms[0];
      if (mode === 'any_of') return { type: 'any_of' as const, patterns: atoms };
      return { type: 'sequence' as const, items: mode === 'gap' ? [atoms[0], { type: 'gap' as const, min: gapMin, max: gapMax }, atoms[1]] : atoms };
    }
    return unit === 'character' ? { ...base, unit, pattern: pattern(values.map(value => ({ type: 'literal' as const, value }))) }
      : { ...base, unit, pattern: pattern(values.map(value => ({ type: 'term' as const, attr: 'form' as const, op: 'eq' as const, value }))) };
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!snapshot) return; setBusy(true); setError('');
    try {
      const input = { snapshot_id: snapshot.id, query: makeQuery(), page_size: 50, context_codepoints: windowSize };
      const operation = `query:${JSON.stringify(input)}`;
      const value = await client.createQuery(projectId, input, key(operation));
      if (!alive.current) return;
      keys.current.delete(operation); await lists(); await selectRun(value.run);
    } catch (cause) { fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function control(action: 'cancel' | 'retry' | 'prepare') {
    if (!run) return; const current = run; setBusy(true); setError('');
    try {
      const requestKey = key(`${action}:${current.id}:${current.attempt}:${current.prepare_state}`);
      const value = action === 'cancel' ? await client.cancelQuery(projectId, current.id, requestKey) : action === 'retry' ? await client.retryQuery(projectId, current.id, requestKey) : await client.prepareResult(projectId, current.result_set_id, requestKey);
      if (alive.current && chosen.current.run === current.id) { generation.current++; setRun(value.run); setContext(undefined); setPageError(''); setCacheMissing(false); if (action === 'retry') { chosen.current.cursor = undefined; setPage(undefined); } }
    } catch (cause) { fail(cause, true); } finally { if (alive.current) setBusy(false); }
  }
  async function pageTo(cursor?: string) {
    if (!run) return; const id = run.id; const epoch = ++generation.current;
    chosen.current.cursor = cursor; setPage(undefined); setContext(undefined); setBusy(true);
    try { await readRun(id, cursor, epoch); } catch (cause) { if (epoch === generation.current) fail(cause, true); }
    finally { if (alive.current) setBusy(false); }
  }
  async function openContext(ordinal: number) {
    if (!run) return; const id = run.id; const epoch = generation.current; setContext(undefined); setBusy(true);
    try { const value = await client.context(projectId, run.result_set_id, ordinal); if (alive.current && epoch === generation.current && chosen.current.run === id) setContext(value); }
    catch (cause) { if (epoch === generation.current) fail(cause, true); } finally { if (alive.current) setBusy(false); }
  }
  async function saveEvidence(ordinal: number) {
    if (!run) return; const current = run; const epoch = generation.current; setBusy(true); setError(''); setOutcomeNotice('');
    const operation = `evidence:${current.result_set_id}:${ordinal}`;
    try { const value = await client.createEvidence(projectId, current.result_set_id, ordinal, key(operation)); if (alive.current && epoch === generation.current && chosen.current.run === current.id) { keys.current.delete(operation); setOutcomeNotice(value.existing ? '该命中已有保存证据，可在“笔记与成果”读取。' : '已保存证据，可在“笔记与成果”引用。'); } }
    catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function exportQuery(format: 'csv' | 'json') {
    if (!run) return; const current = run; setBusy(true); setError(''); const epoch = generation.current; const operation = `export:${current.id}:${format}`;
    try { const value = await client.createExport(projectId, { target: { kind: 'query_runs', query_run_ids: [current.id] }, format }, key(operation)); if (alive.current && epoch === generation.current) { keys.current.delete(operation); onExportCreated(value.export_id); } }
    catch (cause) { if (epoch === generation.current) fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  return <section className="research">
    <div className="section-title"><h2>语料检索</h2><button disabled={busy} onClick={() => void refresh()}>刷新</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    <label>研究快照<select value={snapshot?.id || ''} disabled={busy} onChange={event => void selectSnapshot(event.target.value)}><option value="">选择固定研究快照</option>{snapshot && !snapshots?.items.some(item => item.id === snapshot.id) && <option value={snapshot.id}>{snapshot.name} · {names[snapshot.state]}</option>}{snapshots?.items.map(item => <option value={item.id} key={item.id}>{item.name} · {names[item.state]}{!item.available ? ' · 不可用' : ''}</option>)}</select></label>
    {snapshots?.next_cursor && <button disabled={busy} onClick={() => void lists(snapshots.next_cursor!).catch(fail)}>查看更多快照</button>}
    {snapshots?.allowed_actions.create && <details><summary>选择材料建立快照</summary><h3>已挂载来源</h3>{mounts?.items.filter(item => item.state === 'ACTIVE' && item.release.available && item.release.searchable).map(item => <label key={item.id} className="selection-row"><input type="checkbox" disabled={busy} checked={mountIds.includes(item.id)} onChange={event => { setSelectionNames(previous => ({ ...previous, [item.id]: `${item.release.source_id} · ${item.release.version}` })); setMountIds(previous => event.target.checked ? [...previous, item.id] : previous.filter(id => id !== item.id)); }}/>{item.release.source_id} · {item.release.version}</label>)}{mounts?.next_cursor && <button disabled={busy} onClick={() => void lists(undefined, undefined, mounts.next_cursor!).catch(fail)}>查看更多挂载</button>}<h3>私有固定修订</h3>{materials && !materials.items.some(item => item.revisions.length) && <p>暂无可选修订</p>}{materials?.items.map(item => item.revisions.length > 0 && <label key={item.id}>{item.name}<select disabled={busy} value={item.revisions.find(revision => revisionIds.includes(revision.id))?.id || ''} onChange={event => { const revision = item.revisions.find(value => value.id === event.target.value); if (revision) setSelectionNames(previous => ({ ...previous, [revision.id]: `${item.name} · 修订 ${revision.revision} · ${revision.language === 'cmn' ? '中文' : '英文'}` })); setRevisionIds(previous => [...previous.filter(id => !item.revisions.some(revision => revision.id === id)), ...(event.target.value ? [event.target.value] : [])]); }}><option value="">不选此文件</option>{item.revisions.map(revision => <option key={revision.id} value={revision.id}>修订 {revision.revision} · {revision.language === 'cmn' ? '中文' : '英文'} · {revision.counts.segments} 句段</option>)}</select></label>)}{materials?.next_cursor && <button disabled={busy} onClick={() => void lists(undefined, undefined, undefined, materials.next_cursor!).catch(fail)}>更多私有材料</button>}<ul className="source-list">{[...mountIds, ...revisionIds].map(id => <li key={id}><span>{selectionNames[id] || id}</span><button disabled={busy} onClick={() => { setMountIds(previous => previous.filter(value => value !== id)); setRevisionIds(previous => previous.filter(value => value !== id)); }}>移除选择</button></li>)}</ul><div className="actions"><span>已选 {mountIds.length + revisionIds.length} 项 / 最多 16 项</span><button disabled={busy || mountIds.length + revisionIds.length < 1 || mountIds.length + revisionIds.length > 16} onClick={() => void createSnapshot()}>建立研究快照</button><button disabled={busy} onClick={() => { setMountIds([]); setRevisionIds([]); }}>清空选择</button></div></details>}
    {snapshots && !snapshots.items.length && <p>暂无研究快照</p>}
    {snapshot && <><dl><div><dt>快照状态</dt><dd>{names[snapshot.state]}{!snapshot.available ? ` · ${reasons[snapshot.unavailable_reason || ''] || '当前不可用'}` : ''}</dd></div><div><dt>固定材料</dt><dd>{snapshot.members.map(item => item.kind === 'whole_source_mount' ? item.source_id : `${materials?.items.find(material => material.id === item.material_id)?.name || `私有材料 ${item.material_id.slice(0, 8)}`} 修订 ${item.revision}（${item.language === 'cmn' ? '中文' : '英文'}）`).join('、')}</dd></div>{snapshot.counts && <><div><dt>句段数 / 词项数</dt><dd>{snapshot.counts.sentences.toLocaleString()} / {snapshot.counts.tokens.toLocaleString()}</dd></div><div><dt>来源句记录 / 上传文件</dt><dd>{snapshot.counts.document_units.source_records.toLocaleString()} / {snapshot.counts.document_units.private_files.toLocaleString()}</dd></div></>}</dl>{snapshot.error && <p className="error" role="alert">{snapshot.error.message}</p>}{snapshot.allowed_actions.retry && <button disabled={busy} onClick={() => void retrySnapshot()}>重试准备快照</button>}
      <form onSubmit={event => void submit(event)}><div className="query-options"><label>查询单位<select value={unit} disabled={busy} onChange={event => setUnit(event.target.value as typeof unit)}><option value="character">字符</option><option value="token">词项 form</option></select></label><label>匹配方式<select value={mode} disabled={busy} onChange={event => setMode(event.target.value as typeof mode)}><option value="single">精确匹配</option><option value="sequence">连续序列</option><option value="gap">有限间隔</option><option value="any_of">任一匹配</option></select></label><label>前后文（码点）<input type="number" min={0} max={200} value={windowSize} onChange={event => setWindowSize(Number(event.target.value))} required/></label></div><label>{mode === 'single' ? '查询内容' : mode === 'gap' ? '前项与后项（每行一项）' : '查询项（每行一项）'}<textarea value={text} onChange={event => setText(event.target.value)} disabled={busy} required/></label>{mode === 'gap' && <div className="query-options"><label>最小间隔（{unit === 'character' ? '码点' : '词项'}）<input type="number" min={0} value={gapMin} onChange={event => setGapMin(Number(event.target.value))} required/></label><label>最大间隔（{unit === 'character' ? '码点' : '词项'}）<input type="number" min={0} value={gapMax} onChange={event => setGapMax(Number(event.target.value))} required/></label></div>}<button type="submit" disabled={busy || snapshot.state !== 'READY' || !snapshot.available}>检索</button></form></>}
    {run && <section className="detail"><div className="section-title"><h2>检索结果</h2><span>{names[run.stage] || names[run.state]}</span></div><p>{run.name}</p><details><summary>本次固定范围</summary><dl><div><dt>研究快照</dt><dd className="digest">{run.snapshot_id}</dd></div><div><dt>查询单位</dt><dd>{run.query.unit === 'character' ? '字符' : '词项'}</dd></div><div><dt>前后文</dt><dd>各 {run.context_codepoints} 码点</dd></div></dl></details><div className="actions">{run.allowed_actions.cancel && <button disabled={busy} onClick={() => void control('cancel')}>取消检索</button>}{run.allowed_actions.retry && <button disabled={busy} onClick={() => void control('retry')}>重试检索</button>}{(run.allowed_actions.prepare || cacheMissing) && <button disabled={busy || run.prepare_state === 'pending'} onClick={() => void control('prepare')}>{run.prepare_state === 'pending' ? '准备读取中…' : '准备读取结果'}</button>}</div>
      <dl><div><dt>已执行查询</dt><dd className="sentence-text">{patternSummary(run.query.pattern, run.query.unit)}</dd></div></dl>
      {run.count_state === 'complete' ? <dl><div><dt>命中次数</dt><dd>{run.total_hits?.toLocaleString()}</dd></div><div><dt>命中句段数</dt><dd>{run.matched_segments?.toLocaleString()}</dd></div><div><dt>{run.document_count_unit === 'uploaded_file' ? '命中文件数' : run.document_count_unit === 'mixed_document_units' ? '文档单位（来源句记录＋上传文件）' : '命中导入句记录数'}</dt><dd>{run.matched_documents?.toLocaleString()}{run.document_count_unit === 'mixed_document_units' && run.matched_document_units && `（${run.matched_document_units.source_records} 来源句记录＋${run.matched_document_units.private_files} 上传文件）`}</dd></div></dl> : <p role="status">{run.count_state === 'failed' ? '完整统计未完成' : '完整统计处理中…'}</p>}
      {outcomeNotice && <p role="status">{outcomeNotice}</p>}{run.count_state === 'complete' && <div className="actions"><button disabled={busy} onClick={() => void exportQuery('csv')}>导出完整 CSV 成果包</button><button disabled={busy} onClick={() => void exportQuery('json')}>导出完整 JSON</button></div>}{run.error && <p className="error" role="alert">{run.error.message}</p>}{pageError && <p className="error" role="alert">{pageError}</p>}
      {!page && run.first_page_state === 'pending' && <p role="status">首屏处理中…</p>}
      {page && <>{page.page_state === 'pending' ? <p role="status">本页等待完整结果</p> : !page.hits.length ? <p>本页无命中</p> : <div className="kwic-scroll"><table className="kwic"><thead><tr><th>序号</th><th>左文</th><th>命中</th><th>右文</th><th>原句</th></tr></thead><tbody>{page.hits.map(hit => <tr key={hit.hit_ref.ordinal}><td>{hit.hit_ref.ordinal + 1}</td><td className="kwic-left">{hit.left}</td><td className="kwic-match">{hit.match}</td><td>{hit.right}</td><td><button disabled={busy || run.count_state !== 'complete'} onClick={() => void openContext(hit.hit_ref.ordinal)}>查看</button>{canSaveEvidence && <button disabled={busy || run.count_state !== 'complete'} onClick={() => void saveEvidence(hit.hit_ref.ordinal)}>保存证据</button>}</td></tr>)}</tbody></table></div>}{page.completeness === 'preview' && <p>当前为首屏预览，完整结果完成后可翻页。</p>}<div className="actions">{chosen.current.cursor && <button disabled={busy} onClick={() => void pageTo()}>返回首屏</button>}{page.next_cursor && <button disabled={busy} onClick={() => void pageTo(page.next_cursor!)}>下一页</button>}<button disabled={busy} onClick={() => void pageTo(chosen.current.cursor)}>重新读取本页</button></div></>}
      {context && <section className="detail"><h3>原句</h3><p className="sentence-text">{Array.from(context.text).slice(0, context.start_cp - context.context_start_cp).join('')}<mark>{Array.from(context.text).slice(context.start_cp - context.context_start_cp, context.end_cp - context.context_start_cp).join('')}</mark>{Array.from(context.text).slice(context.end_cp - context.context_start_cp).join('')}</p><dl><div><dt>{context.origin_kind === 'private' ? '文件' : '来源句编号'}</dt><dd>{context.origin_kind === 'private' ? context.document_name : context.source_sentence_id}</dd></div><div><dt>正文码点区间</dt><dd>[{context.start_cp}, {context.end_cp})</dd></div>{context.token_start !== null && <div><dt>句内词项区间</dt><dd>[{context.token_start}, {context.token_end})</dd></div>}</dl>{context.source_url && /^https?:\/\//.test(context.source_url) && <a href={context.source_url} target="_blank" rel="noreferrer">查看来源</a>}</section>}
    </section>}
    <details className="query-history"><summary>检索历史{history ? `（${history.total}）` : ''}</summary>{history && !history.items.length ? <p>暂无检索记录</p> : <ul className="source-list">{history?.items.map(item => <li key={item.id}><button onClick={() => void selectRun(item)} disabled={busy}>{item.name} · {names[item.state]}<time>{new Date(item.created_at).toLocaleString()}</time></button></li>)}</ul>}<div className="actions"><button disabled={busy} onClick={() => void lists().catch(fail)}>返回首批</button>{history?.next_cursor && <button disabled={busy} onClick={() => void lists(undefined, history.next_cursor!).catch(fail)}>查看更多记录</button>}</div></details>
  </section>;
}
