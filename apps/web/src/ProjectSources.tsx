import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, CorpusApiClient } from '../../../contracts/types/s1';
import type { SourceList, SourceVersionList } from '../../../contracts/types/catalog';
import type { MountList, MountManifest } from '../../../contracts/types/source-release';

export function ProjectSources({ client, projectId, onUnauthorized }: { client: CorpusApiClient; projectId: string; onUnauthorized: (cause: unknown) => void }) {
  const [listing, setListing] = useState<MountList>();
  const [sources, setSources] = useState<SourceList>();
  const [source, setSource] = useState('');
  const [versions, setVersions] = useState<SourceVersionList>();
  const [snapshot, setSnapshot] = useState('');
  const [manifest, setManifest] = useState<MountManifest>();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const key = useRef<{ payload: string; id: string } | undefined>(undefined);
  const cursor = useRef<string | undefined>(undefined);
  const reasons: Record<string, string> = { SOURCE_POLICY_DENIED: '该固定版本当前未获准用于内部研究', SOURCE_IDENTITY_CHANGED: '来源身份已变更，须重新核准', SOURCE_POLICY_MISMATCH: '核准依据与固定版本不一致', INDEX_NOT_AVAILABLE: '固定索引暂不可访问' };
  function fail(cause: unknown) {
    setManifest(undefined);
    if (cause instanceof ApiError) {
      if (cause.status === 401) onUnauthorized(cause);
      if (['PROJECT_NOT_FOUND', 'PROJECT_FORBIDDEN', 'FORBIDDEN'].includes(cause.code)) { setListing(undefined); setSources(undefined); setVersions(undefined); setSnapshot(''); }
      if (cause.code.startsWith('SOURCE_POLICY_') || cause.code === 'SOURCE_IDENTITY_CHANGED') { setVersions(undefined); setSnapshot(''); setSource(''); }
    }
    setError(cause instanceof Error ? cause.message : '请求失败，请重试。');
  }
  async function action(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try { await work(); } catch (cause) { if (mounted.current) fail(cause); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  async function read() { const value = await client.mounts(projectId, cursor.current, 20); if (mounted.current) { setListing(value); setManifest(undefined); } }
  useEffect(() => { mounted.current = true; void action(read); return () => { mounted.current = false; }; }, []);
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const q = String(new FormData(event.currentTarget).get('q') || '');
    await action(async () => { const value = await client.sources({ q, page_size: 100 }); if (mounted.current) { setSources(value); setSource(''); setVersions(undefined); setSnapshot(''); } });
  }
  async function selectSource(id: string, next?: string) {
    await action(async () => { const value = await client.sourceVersions(id, next, 50); if (mounted.current) { setSource(id); setVersions(value); setSnapshot(''); } });
  }
  function mutationKey(payload: unknown) { const encoded = JSON.stringify(payload); if (key.current?.payload !== encoded) key.current = { payload: encoded, id: crypto.randomUUID() }; return key.current.id; }
  async function change(operation: 'create' | 'remove', target: string) {
    await action(async () => {
      const mutation = mutationKey([operation, projectId, target]);
      const result = operation === 'create' ? await client.createMount(projectId, target, mutation) : await client.removeMount(projectId, target, mutation);
      if (!mounted.current) return;
      key.current = undefined; cursor.current = undefined; setNotice(operation === 'remove' ? '已移除挂载，保留历史记录。' : result.existing ? '该固定版本已挂载。' : '已挂载固定版本。'); await read();
    });
  }
  return <section className="source-sync"><div className="section-title"><h2>项目来源</h2><button disabled={busy} onClick={() => void action(read)}>刷新挂载</button></div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{busy && <p role="status">处理中…</p>}
    {listing?.allowed_actions.create && <><form className="actions" onSubmit={event => void search(event)}><label>选择来源<input name="q" placeholder="名称或编号" maxLength={160} disabled={busy}/></label><button disabled={busy} type="submit">查找发布版本</button></form>
      {sources && (sources.items.length ? <label>来源<select value={source} disabled={busy} onChange={event => { if (event.target.value) void selectSource(event.target.value); }}><option value="">请选择来源</option>{sources.items.map(item => <option key={item.source_id} value={item.source_id}>{item.source_id} · {item.name}</option>)}</select></label> : <p>没有符合条件的来源</p>)}
      {versions && (versions.items.length ? <><label>固定发布版本<select value={snapshot} disabled={busy} onChange={event => setSnapshot(event.target.value)}><option value="">请选择发布版</option>{versions.items.map(item => <option key={item.release_id} value={item.source_snapshot_id} disabled={!item.available}>{item.version} · {new Date(item.published_at).toLocaleString()} · {item.available ? '允许挂载' : '当前不可挂载'}</option>)}</select></label>{snapshot && <p className="digest">固定快照：{snapshot}</p>}<button disabled={busy || !snapshot} onClick={() => void change('create', snapshot)}>整库挂载</button>{versions.next_cursor && <button disabled={busy} onClick={() => void selectSource(source, versions.next_cursor!)}>查看更多发布版</button>}</> : <p>该来源暂无已发布版本</p>)}</>}
    {listing && <><p>共 {listing.total} 条挂载记录</p>{!listing.items.length ? <p>尚未挂载来源</p> : <ul className="jobs">{listing.items.map(item => <li key={item.id}><strong>{item.release.source_id} · {item.release.version}</strong><dl><div><dt>挂载状态</dt><dd>{item.state === 'REMOVED' ? '已移除' : item.release.available ? '有效挂载' : '许可受限'}</dd></div><div><dt>正文检索</dt><dd>{item.state === 'ACTIVE' && item.release.searchable ? '可建立研究快照' : '尚不可检索'}</dd></div><div><dt>固定快照</dt><dd className="digest">{item.release.source_snapshot_id}</dd></div><div><dt>句子数</dt><dd>{typeof item.release.counts.sentences === 'number' ? item.release.counts.sentences.toLocaleString() : '未知'}</dd></div></dl>{item.release.unavailable_reason && <p>{reasons[item.release.unavailable_reason] || '该版本当前不可挂载或读取'}</p>}<div className="actions">{item.allowed_actions.read_manifest && <button disabled={busy} onClick={() => void action(async () => { const value = await client.mountManifest(projectId, item.id); if (mounted.current) setManifest(value); })}>读取固定清单</button>}{item.allowed_actions.remove && <button disabled={busy} onClick={() => void change('remove', item.id)}>移除挂载</button>}</div></li>)}</ul>}<div className="actions">{cursor.current && <button disabled={busy} onClick={() => { cursor.current = undefined; void action(read); }}>返回首批</button>}{listing.next_cursor && <button disabled={busy} onClick={() => { cursor.current = listing.next_cursor!; void action(read); }}>查看更多挂载</button>}</div></>}
    {manifest && <section className="detail"><h3>固定清单</h3><dl><div><dt>快照</dt><dd className="digest">{manifest.source_snapshot_id}</dd></div><div><dt>清单 SHA-256</dt><dd className="digest">{manifest.manifest_sha256}</dd></div></dl><details open><summary>清单内容</summary><pre className="manifest-content">{JSON.stringify(manifest.manifest, null, 2)}</pre></details></section>}
  </section>;
}
