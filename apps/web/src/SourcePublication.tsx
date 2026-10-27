import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, CorpusApiClient } from '../../../contracts/types/s1';
import type { PolicyInput, PolicyView, ReleaseView } from '../../../contracts/types/source-release';

export function SourcePublication({ client, sourceId, acquisitionId, indexId, onUnauthorized }: { client: CorpusApiClient; sourceId: string; acquisitionId: string; indexId: string; onUnauthorized: (cause: unknown) => void }) {
  const [policy, setPolicy] = useState<PolicyView>();
  const [release, setRelease] = useState<ReleaseView>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mounted = useRef(true);
  const inFlight = useRef(false);
  const key = useRef<{ payload: string; id: string } | undefined>(undefined);
  const licenseEvidence = Array.isArray(policy?.license.evidence) ? policy.license.evidence.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null) : [];
  function fail(cause: unknown) { if (cause instanceof ApiError && cause.status === 401) onUnauthorized(cause); if (cause instanceof ApiError && cause.status === 403) { setPolicy(undefined); setRelease(undefined); } setError(cause instanceof Error ? cause.message : '操作失败，请重试。'); }
  async function read() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setRelease(undefined);
    try { const value = await client.sourcePolicy(sourceId, acquisitionId); if (mounted.current) setPolicy(value); }
    catch (cause) { if (mounted.current) fail(cause); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  useEffect(() => { mounted.current = true; void read(); return () => { mounted.current = false; }; }, []);
  function mutationKey(payload: unknown) { const encoded = JSON.stringify(payload); if (key.current?.payload !== encoded) key.current = { payload: encoded, id: crypto.randomUUID() }; return key.current.id; }
  async function approve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!policy || inFlight.current) return;
    const form = event.currentTarget; const data = new FormData(form);
    const input: PolicyInput = { expected_revision: policy.revision, decision: String(data.get('decision')) as PolicyInput['decision'], export_decision: String(data.get('export_decision')) as PolicyInput['export_decision'], review_note: String(data.get('review_note')).trim(), evidence_urls: String(data.get('evidence_urls')).split(/\r?\n/).map(value => value.trim()).filter(Boolean) };
    if (!['allow', 'deny'].includes(input.decision) || !['allow', 'deny'].includes(input.export_decision || '')) return;
    inFlight.current = true; setBusy(true); setError(''); setNotice('');
    try { const result = await client.updateSourcePolicy(sourceId, acquisitionId, input, mutationKey(['policy', sourceId, acquisitionId, input])); if (mounted.current) { setPolicy(result.policy); setRelease(undefined); key.current = undefined; setNotice('已保存该采集版本的策略。'); form.reset(); } }
    catch (cause) { if (mounted.current) fail(cause); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  async function publish() {
    if (!policy || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setNotice('');
    try { const result = await client.publishRelease(sourceId, indexId, policy.revision, mutationKey(['publish', sourceId, indexId, policy.revision])); if (mounted.current) { setRelease(result.release); key.current = undefined; setNotice(result.existing ? '该索引已有发布版，读取原版本。' : '已发布固定版本。'); } }
    catch (cause) { if (mounted.current) fail(cause); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  return <section className="source-sync"><div className="section-title"><h3>核准与发布</h3><button disabled={busy} onClick={() => void read()}>读取当前策略</button></div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{busy && <p role="status">处理中…</p>}
    {policy && <><dl><div><dt>内部研究许可</dt><dd>{{ unknown: '尚未核准', allow: '允许', deny: '拒绝' }[policy.decision]} · 修订 {policy.revision}</dd></div><div><dt>来源身份</dt><dd>{policy.identity_current ? '与核准依据一致' : '已变更，原核准无效'}</dd></div><div><dt>导出许可</dt><dd>{policy.export ? '允许此采集版本导出' : '未允许'}</dd></div><div><dt>模型外发</dt><dd>未批准</dd></div></dl>
      {policy.review_note && <p>核准依据：{policy.review_note}</p>}
      <details><summary>采集许可与核准记录</summary><dl><div><dt>采集版本</dt><dd className="digest">{acquisitionId}</dd></div><div><dt>许可声明</dt><dd>{typeof policy.license.declared === 'string' ? policy.license.declared : '见许可记录'}</dd></div><div><dt>归属人未知</dt><dd>{typeof policy.quality.unknown_owner === 'number' ? policy.quality.unknown_owner.toLocaleString() : '未知'}</dd></div><div><dt>缺失端点关系行</dt><dd>{typeof policy.quality.missing_endpoint_rows === 'number' ? policy.quality.missing_endpoint_rows.toLocaleString() : '未知'}</dd></div><div><dt>许可摘要</dt><dd className="digest">{policy.license_sha256}</dd></div><div><dt>核准时间</dt><dd>{policy.reviewed_at ? new Date(policy.reviewed_at).toLocaleString() : '尚未核准'}</dd></div></dl>{policy.evidence_urls.map(url => <p key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></p>)}</details>
      {licenseEvidence.length > 0 && <details><summary>采集时许可依据</summary>{licenseEvidence.map((item, index) => <dl key={index}>{typeof item.url === 'string' && /^https?:\/\//.test(item.url) && <div><dt>依据地址</dt><dd><a href={item.url} target="_blank" rel="noreferrer">{item.url}</a></dd></div>}{typeof item.sha256 === 'string' && <div><dt>保存摘要</dt><dd className="digest">{item.sha256}</dd></div>}</dl>)}</details>}
      <form onSubmit={event => void approve(event)}><label>内部研究决定<select name="decision" required defaultValue="" disabled={busy}><option value="" disabled>请选择</option><option value="allow">允许此采集版本用于内部研究</option><option value="deny">拒绝此采集版本用于内部研究</option></select></label><label>导出决定<select name="export_decision" required defaultValue="" disabled={busy}><option value="" disabled>请选择</option><option value="allow">允许此采集版本导出</option><option value="deny">拒绝此采集版本导出</option></select></label><label>核准依据<textarea name="review_note" required maxLength={4000} disabled={busy}/></label><label>依据地址（每行一个）<textarea name="evidence_urls" required disabled={busy}/></label><button disabled={busy} type="submit">保存策略</button></form>
      <button disabled={busy || policy.decision !== 'allow' || !policy.identity_current} onClick={() => void publish()}>发布此固定索引</button></>}
    {release && <dl><div><dt>发布版本</dt><dd>{release.version}</dd></div><div><dt>当前挂载许可</dt><dd>{release.available ? '允许挂载' : release.unavailable_reason || '不可挂载'}</dd></div><div><dt>正文检索</dt><dd>{release.searchable ? '可在项目研究快照中检索' : '尚不可检索'}</dd></div><div><dt>固定快照</dt><dd className="digest">{release.source_snapshot_id}</dd></div></dl>}
  </section>;
}
