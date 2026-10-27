import { SourceIndex } from './SourceIndex';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, CorpusApiClient } from '../../../contracts/types/s1';
import type { CatalogCreate, CatalogMetadata, EntryKind, SourceFilters, SourceList, SourceView, SourceVersionList } from '../../../contracts/types/catalog';
import { SourceSync } from './SourceSync';

const statuses = { catalog_only: '仅目录登记', verification_pending: '待核验', experimental_evidence: '已有实验记录' };
const kinds = { publisher: '发布方', aggregator: '聚合入口', dataset: '数据集' };
const capabilities = { discover: '目录发现', remote_query: '远程查询', fulltext_analysis: '全文分析', export: '导出', model_egress: '模型外发' };
const categoryLabels: Record<string, string> = { academic: '学术', dialects: '方言', english: '英语语料', historical: '历史语料', learners: '学习者', lexicon: '词典与词汇', literature: '文学', multilingual: '多语', news_web: '新闻与网络', parallel: '平行语料', repository: '数据仓储', spoken: '口语', treebank: '树库', zh_historical: '古汉语', zh_modern: '现代汉语' };
const languageLabels: Record<string, string> = { zh: '中文', en: '英文', mul: '多语', de: '德语', es: '西班牙语', fr: '法语', ja: '日语', ko: '韩语' };
const metadataOf = (source: SourceView): CatalogMetadata => ({ name: source.name, publisher: source.publisher, entry_kind: source.entry_kind, categories: source.categories, languages: source.languages, official_url: source.official_url, materials: source.materials, access_route: source.access_route, boundary: source.boundary });

export function Catalog({ client, admin, onUnauthorized }: { client: CorpusApiClient; admin: boolean; onUnauthorized: (cause: unknown) => void }) {
  const [listing, setListing] = useState<SourceList>();
  const [filters, setFilters] = useState<SourceFilters>({});
  const [source, setSource] = useState<SourceView>();
  const [versions, setVersions] = useState<SourceVersionList>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [readFailed, setReadFailed] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const [indexOpen, setIndexOpen] = useState(false);
  const lastRead = useRef<{ kind: 'list'; filters: SourceFilters } | { kind: 'detail'; id: string }>({ kind: 'list', filters: {} });
  const [editing, setEditing] = useState<'create' | 'update'>();
  const [classifications, setClassifications] = useState({ languages: [] as string[], categories: [] as string[] });
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const mutationKey = useRef<{ payload: string; key: string } | undefined>(undefined);
  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) onUnauthorized(cause);
    const messages: Record<string, string> = { ADMIN_REQUIRED: '需要平台管理员权限。', REVISION_CONFLICT: '目录已被修改，请重新读取后编辑。', SOURCE_EXISTS: '该来源编号已存在。', SOURCE_NOT_FOUND: '来源不存在。', IDEMPOTENCY_CONFLICT: '提交标识与原参数不一致，请重新编辑后提交。', VALIDATION_ERROR: '登记内容无效，请检查字段和官方依据地址。' };
    setError(cause instanceof ApiError ? messages[cause.code] || cause.message : cause instanceof Error ? cause.message : '请求失败，请重试。');
  }
  async function load(value: SourceFilters) {
    const request = ++listRequest.current; setLoading(true); setError(''); setReadFailed(false); lastRead.current = { kind: 'list', filters: value };
    try {
      const response = await client.sources(value);
      if (request !== listRequest.current) return;
      setListing(response); setFilters(value);
      if (!Object.keys(value).length) setClassifications({ languages: [...new Set(response.items.flatMap(item => item.languages))].sort(), categories: [...new Set(response.items.flatMap(item => item.categories))].sort() });
    } catch (cause) { if (request === listRequest.current) { setReadFailed(true); fail(cause); } }
    finally { if (request === listRequest.current) setLoading(false); }
  }
  async function open(id: string) {
    const request = ++detailRequest.current; setDetailLoading(true); setSource(undefined); setVersions(undefined); setEditing(undefined); setSyncOpen(false); setIndexOpen(false); setError(''); setReadFailed(false); lastRead.current = { kind: 'detail', id };
    try {
      const [value, releases] = await Promise.all([client.source(id), client.sourceVersions(id)]);
      if (request !== detailRequest.current) return;
      setSource(value); setVersions(releases);
    } catch (cause) { if (request === detailRequest.current) { setReadFailed(true); fail(cause); } }
    finally { if (request === detailRequest.current) setDetailLoading(false); }
  }
  useEffect(() => { void load({}); return () => { listRequest.current++; detailRequest.current++; }; }, []);
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); const value: Record<string, string> = {};
    detailRequest.current++; setSource(undefined); setVersions(undefined); setEditing(undefined); setDetailLoading(false);
    for (const field of ['q', 'language', 'category', 'status', 'capability']) { const item = String(data.get(field) || '').trim(); if (item) value[field] = item; }
    void load(value as SourceFilters);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!admin || !editing) return;
    const data = new FormData(event.currentTarget);
    const field = (key: string) => String(data.get(key) || '').trim();
    const tags = (key: string) => field(key).split(/[,，]/).map(value => value.trim()).filter(Boolean);
    const metadata: CatalogMetadata = { name: field('name'), publisher: field('publisher'), entry_kind: field('entry_kind') as EntryKind, categories: tags('categories'), languages: tags('languages'), official_url: field('official_url'), materials: field('materials'), access_route: field('access_route'), boundary: field('boundary') };
    const input = editing === 'create' ? { ...metadata, source_id: field('source_id') } : { ...metadata, expected_revision: source!.revision };
    const payload = JSON.stringify([editing, source?.source_id, input]);
    if (mutationKey.current?.payload !== payload) mutationKey.current = { payload, key: crypto.randomUUID() };
    setSaving(true); setError('');
    try {
      const result = editing === 'create' ? await client.createCatalog(input as CatalogCreate, mutationKey.current.key) : await client.updateCatalog(source!.source_id, { ...metadata, expected_revision: source!.revision }, mutationKey.current.key);
      setSource(result); setEditing(undefined); setVersions(await client.sourceVersions(result.source_id));
      const { cursor: _cursor, ...current } = filters; await load(current);
    } catch (cause) { fail(cause); } finally { setSaving(false); }
  }
  const draft = editing === 'update' && source ? metadataOf(source) : undefined;
  return <section className="catalog">
    <div className="section-title"><h2>来源目录</h2>{admin && <button disabled={saving} onClick={() => { detailRequest.current++; setDetailLoading(false); setSource(undefined); setVersions(undefined); setEditing('create'); setError(''); }}>登记来源</button>}</div>
    <form className="catalog-filters" onSubmit={search}>
      <label>名称、编号或发布方<input name="q" maxLength={160}/></label>
      <label>语言<select name="language"><option value="">全部</option>{[...new Set([...Object.keys(languageLabels), ...classifications.languages])].map(value => <option key={value} value={value}>{languageLabels[value] || value}</option>)}</select></label>
      <label>类别<select name="category"><option value="">全部</option>{[...new Set([...Object.keys(categoryLabels), ...classifications.categories])].map(value => <option key={value} value={value}>{categoryLabels[value] || value}</option>)}</select></label>
      <label>接入状态<select name="status"><option value="">全部</option>{Object.entries(statuses).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
      <label>能力<select name="capability"><option value="">全部</option>{Object.entries(capabilities).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
      <button disabled={loading || saving} type="submit">搜索</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {readFailed && <button disabled={loading || detailLoading} onClick={() => { const read = lastRead.current; void (read.kind === 'list' ? load(read.filters) : open(read.id)); }}>重新读取</button>}
    <div className="catalog-layout"><div>
    {loading ? <p role="status">正在读取目录…</p> : listing && <><p>共 {listing.total} 项登记</p>{listing.items.length === 0 ? <p>没有符合条件的来源</p> : <ul className="source-list">{listing.items.map(item => <li key={item.source_id}><button disabled={saving} onClick={() => void open(item.source_id)}><strong>{item.source_id}　{item.name}</strong><span>{item.publisher}</span><span>{item.languages.map(value => languageLabels[value] || value).join('、')} · {item.categories.map(value => categoryLabels[value] || value).join('、')}</span><span>{statuses[item.integration_status]} · 许可待审核</span></button></li>)}</ul>}<div className="actions">{filters.cursor && <button disabled={saving} onClick={() => { const { cursor: _cursor, ...value } = filters; void load(value); }}>返回第一页</button>}{listing.next_cursor && <button disabled={saving} onClick={() => void load({ ...filters, cursor: listing.next_cursor! })}>下一页</button>}</div></>}
    </div><div>
    {detailLoading && <p role="status">正在读取来源…</p>}
    {admin && source && !editing && <div className="actions"><button aria-pressed={!syncOpen && !indexOpen} onClick={() => { setSyncOpen(false); setIndexOpen(false); }}>来源详情</button>{source.source_id === 'D12' && <button aria-pressed={syncOpen} onClick={() => { setSyncOpen(true); setIndexOpen(false); }}>同步管理</button>}<button aria-pressed={indexOpen} onClick={() => { setIndexOpen(true); setSyncOpen(false); }}>核准与发布</button></div>}
    {source && !editing && !(admin && (syncOpen || indexOpen)) && <section className="detail"><div className="section-title"><h2>{source.name}</h2>{admin && <button disabled={saving} onClick={() => setEditing('update')}>编辑登记</button>}</div><dl>
      <div><dt>编号</dt><dd>{source.source_id}</dd></div><div><dt>发布方</dt><dd>{source.publisher}</dd></div><div><dt>登记类型</dt><dd>{kinds[source.entry_kind]}</dd></div><div><dt>官方依据</dt><dd><a href={source.official_url} target="_blank" rel="noreferrer">{source.official_url}</a></dd></div>
      <div><dt>材料</dt><dd>{source.materials}</dd></div><div><dt>获取方式</dt><dd>{source.access_route}</dd></div><div><dt>使用边界</dt><dd>{source.boundary}</dd></div><div><dt>接入状态</dt><dd>{statuses[source.integration_status]}</dd></div><div><dt>许可</dt><dd>待审核</dd></div>
      {Object.entries(capabilities).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{source.capabilities[key as keyof typeof capabilities] ? '可用' : '未开放'}</dd></div>)}
    </dl><div className="section-title"><h2>已发布版本</h2><button disabled={saving} onClick={() => void open(source.source_id)}>刷新版本</button></div>{versions?.items.length ? <ul>{versions.items.map(item => <li key={item.release_id}>{item.version} · {new Date(item.published_at).toLocaleString()} · {item.available ? '允许项目挂载' : '当前不可挂载'} · {item.searchable ? '可在项目快照中检索' : '尚不可检索'}<p className="digest">{item.manifest_sha256}</p></li>)}</ul> : <p>暂无已发布版本</p>}{source.evidence_refs.length > 0 && <details><summary>实验记录</summary><ul>{source.evidence_refs.map(item => <li className="digest" key={item}>{item}</li>)}</ul></details>}<details><summary>登记记录</summary><p>修订 {source.revision} · {new Date(source.updated_at).toLocaleString()}</p></details></section>}
    {admin && source?.source_id === 'D12' && !editing && syncOpen && <SourceSync key={source.source_id} client={client} onUnauthorized={onUnauthorized}/>}
    {admin && source && !editing && indexOpen && <SourceIndex key={source.source_id} client={client} sourceId={source.source_id} onUnauthorized={onUnauthorized}/>}
    {editing && admin && <form className="catalog-editor detail" key={`${editing}:${source?.source_id}:${source?.revision}`} onSubmit={event => void save(event)}><h2>{editing === 'create' ? '登记来源' : `编辑 ${source!.source_id}`}</h2>
      {editing === 'create' && <label>来源编号<input name="source_id" required pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" maxLength={64} disabled={saving}/></label>}
      <label>名称<input name="name" required maxLength={160} defaultValue={draft?.name} disabled={saving}/></label><label>发布方<input name="publisher" required maxLength={200} defaultValue={draft?.publisher} disabled={saving}/></label>
      <label>登记类型<select name="entry_kind" defaultValue={draft?.entry_kind || 'dataset'} disabled={saving}>{Object.entries(kinds).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
      <label>类别（逗号分隔）<input name="categories" required defaultValue={draft?.categories.join('，')} disabled={saving}/></label><label>语言（逗号分隔）<input name="languages" required defaultValue={draft?.languages.join('，')} disabled={saving}/></label>
      <label>官方依据<input name="official_url" type="url" required maxLength={2048} defaultValue={draft?.official_url} disabled={saving}/></label>
      {(['materials', 'access_route', 'boundary'] as const).map((field, index) => <label key={field}>{['材料', '获取方式', '使用边界'][index]}<textarea name={field} required maxLength={field === 'boundary' ? 4000 : 2000} defaultValue={draft?.[field]} disabled={saving}/></label>)}
      <div className="actions"><button disabled={saving} type="submit">{saving ? '保存中…' : '保存登记'}</button><button disabled={saving} type="button" onClick={() => setEditing(undefined)}>取消</button>{editing === 'update' && <button disabled={saving} type="button" onClick={() => void open(source!.source_id)}>重新读取</button>}</div>
    </form>}
    </div></div>
  </section>;
}
