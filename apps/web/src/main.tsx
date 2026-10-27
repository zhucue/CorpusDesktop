import { AgentWorkspace } from './AgentWorkspace';
import type { AgentResultView, AgentScope } from '../../../contracts/types/agent';
import { Outcomes } from './Outcomes';
import { PrivateMaterials } from './PrivateMaterials';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { ApiError, CorpusApiClient, type AuthView, type JobView, type ProjectView, type UploadView } from '../../../contracts/types/s1';
import './style.css';
import { ProjectSources } from './ProjectSources';
import { Catalog } from './Catalog';
import { Research } from './Research';

const stateNames: Record<string, string> = { QUEUED: '排队中', RUNNING: '校验中', CANCEL_REQUESTED: '取消中', CANCELLED: '已取消', SUCCEEDED: '已校验', FAILED: '失败' };
const roles = { owner: '负责人', editor: '编辑', viewer: '只读' };
const mediaTypes: Record<string, string> = { txt: 'text/plain', csv: 'text/csv', tsv: 'text/tab-separated-values', json: 'application/json', jsonl: 'application/x-ndjson' };
const sizeLabel = (size: number) => size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;

function App() {
  const [auth, setAuth] = useState<AuthView>();
  const [page, setPage] = useState<'assistant' | 'projects' | 'catalog'>('assistant');
  const [outcomeExport, setOutcomeExport] = useState<string>();
  const [projectPage, setProjectPage] = useState<'materials' | 'research' | 'outcomes'>('materials');
  const outcomeLeaveGuard = useRef<(() => boolean) | undefined>(undefined);
  function canLeaveOutcomes() { return outcomeLeaveGuard.current?.() ?? true; }
  function changeProjectPage(value: typeof projectPage) { if (value === projectPage || canLeaveOutcomes()) setProjectPage(value); }
  function changePage(value: typeof page) { if (value === page || canLeaveOutcomes()) setPage(value); }
  const authRef = useRef<AuthView | undefined>(undefined);
  const client = useRef(new CorpusApiClient({ csrf: () => authRef.current?.csrf_token })).current;
  const [restoring, setRestoring] = useState(true);
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [project, setProject] = useState<ProjectView>();
  const projectRef = useRef<string | undefined>(undefined);
  const [jobs, setJobs] = useState<JobView[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const jobsRequest = useRef(0);
  const pageCursor = useRef<string | undefined>(undefined);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File>();
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadStage, setUploadStage] = useState('');
  const [pendingUpload, setPendingUpload] = useState<{ view: UploadView; completeKey: string }>();
  const [selectedJob, setSelectedJob] = useState<JobView>();
  const fileInput = useRef<HTMLInputElement>(null);
  const requestEpoch = useRef(0);
  const jobActionKeys = useRef(new Map<string, string>());
  const [theme, setTheme] = useState(() => localStorage.getItem('corpus-theme') || 'system');
  function setIdentity(value?: AuthView) { authRef.current = value; setAuth(value); }
  function clearProject() { setOutcomeExport(undefined); requestEpoch.current++; jobsRequest.current++; pageCursor.current = undefined; projectRef.current = undefined; setProject(undefined); setJobs([]); setNextCursor(null); setFile(undefined); setPendingUpload(undefined); setSelectedJob(undefined); setUploadStage(''); setUploadProgress(null); }
  function showError(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) { setIdentity(undefined); clearProject(); setProjects([]); }
    setError(cause instanceof Error ? cause.message : '请求失败，请重试。');
  }
  async function loadProjects() { const response = await client.projects(); setProjects(response.items); }
  async function refreshJobs(id: string) {
    const sequence = ++jobsRequest.current;
    const [current, response] = await Promise.all([client.project(id), client.jobs(id, pageCursor.current)]);
    if (projectRef.current !== id || sequence !== jobsRequest.current) return;
    setProject(current); setJobs(response.items); setNextCursor(response.next_cursor);
    setSelectedJob(previous => previous ? response.items.find(item => item.job_id === previous.job_id) : undefined);
  }
  async function moreJobs() {
    if (!project || !nextCursor) return;
    setBusy(true); const id = project.id; pageCursor.current = nextCursor;
    try { await refreshJobs(id); }
    catch (cause) { showError(cause); } finally { setBusy(false); }
  }
  useEffect(() => {
    void client.session().then(value => { setIdentity(value); return loadProjects(); }).catch(cause => {
      if (!(cause instanceof ApiError && cause.status === 401)) showError(cause);
    }).finally(() => setRestoring(false));
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('corpus-theme', theme); }, [theme]);
  useEffect(() => {
    if (!project) return;
    const id = project.id;
    const timer = window.setInterval(() => void refreshJobs(id).catch(cause => {
      if (projectRef.current !== id) return;
      if (cause instanceof ApiError && [403, 404].includes(cause.status)) clearProject();
      showError(cause);
    }), 2500);
    return () => window.clearInterval(timer);
  }, [project?.id]);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = event.currentTarget; const values = new FormData(form);
    try { const value = await client.login(String(values.get('email')), String(values.get('password'))); form.reset(); setIdentity(value); await loadProjects(); }
    catch (cause) { form.querySelector<HTMLInputElement>('[name=password]')!.value = ''; showError(cause); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (!canLeaveOutcomes()) return;
    setBusy(true); setError('');
    try { await client.logout(); setIdentity(undefined); clearProject(); setProjects([]); }
    catch (cause) { showError(cause); } finally { setBusy(false); }
  }
  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!canLeaveOutcomes()) return; setBusy(true); setError(''); const form = event.currentTarget;
    try { const value = await client.createProject(String(new FormData(form).get('name'))); form.reset(); await loadProjects(); await openProject(value.id, true); }
    catch (cause) { showError(cause); } finally { setBusy(false); }
  }
  async function openProject(id: string, leaveConfirmed = false) {
    if (!leaveConfirmed && !canLeaveOutcomes()) return;
    clearProject(); const epoch = requestEpoch.current; setError('');
    try { const value = await client.project(id); if (epoch !== requestEpoch.current) return; projectRef.current = id; setProject(value); await refreshJobs(id); }
    catch (cause) { if (epoch === requestEpoch.current) showError(cause); }
  }
  function putFile(view: UploadView, value: File) {
    return new Promise<void>((resolve, reject) => {
      const url = new URL(view.upload_url, window.location.origin);
      if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/v1/uploads/')) { reject(new Error('上传地址无效')); return; }
      const xhr = new XMLHttpRequest(); xhr.open('PUT', url.href); xhr.withCredentials = true; xhr.timeout = 120000;
      xhr.setRequestHeader('X-CSRF-Token', authRef.current?.csrf_token || ''); xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = event => { if (event.lengthComputable) setUploadProgress(event.loaded / event.total); };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else { let message = '文件传输失败'; try { message = JSON.parse(xhr.responseText).message || message; } catch { /* Non-JSON transport failure. */ } reject(new ApiError(xhr.status, { message })); }
      };
      xhr.onerror = () => reject(new Error('文件传输中断，请重新选择文件上传。'));
      xhr.ontimeout = () => reject(new Error('文件传输超时，请重新上传。')); xhr.send(value);
    });
  }
  async function completeUpload(pending: { view: UploadView; completeKey: string }) {
    const response = await client.completeUpload(pending.view.upload_id, pending.completeKey);
    pageCursor.current = undefined;
    setPendingUpload(undefined); setFile(undefined); if (fileInput.current) fileInput.current.value = '';
    setUploadProgress(null); setUploadStage('');
    if (projectRef.current) { await refreshJobs(projectRef.current); setSelectedJob(await client.job(response.job_id)); }
  }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!file || !project) return; setBusy(true); setError(''); setUploadProgress(null);
    try {
      if (file.size < 1 || file.size > 100000000) throw new Error('请选择 1 B 至 100 MB 的文件。');
      const media_type = mediaTypes[file.name.split('.').pop()?.toLowerCase() || ''];
      if (!media_type) throw new Error('请选择 TXT、CSV、TSV、JSON 或 JSONL 文件。');
      setUploadStage('计算文件摘要'); const bytes = await file.arrayBuffer();
      const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(value => value.toString(16).padStart(2, '0')).join('');
      const view = await client.createUpload(project.id, { filename: file.name, size: file.size, media_type, sha256 }, crypto.randomUUID());
      setUploadStage('传输文件'); await putFile(view, file);
      const pending = { view, completeKey: crypto.randomUUID() }; setPendingUpload(pending);
      setUploadStage('提交校验任务'); await completeUpload(pending);
    } catch (cause) { showError(cause); setUploadStage(''); } finally { setBusy(false); }
  }
  async function retryComplete() {
    if (!pendingUpload) return; setBusy(true); setError('');
    try { await completeUpload(pendingUpload); } catch (cause) { showError(cause); } finally { setBusy(false); }
  }
  async function jobAction(job: JobView, action: 'cancel' | 'retry') {
    setBusy(true); setError(''); const operation = `${job.job_id}:${action}:${job.attempt}`;
    const key = jobActionKeys.current.get(operation) || crypto.randomUUID(); jobActionKeys.current.set(operation, key);
    try { await (action === 'cancel' ? client.cancelJob(job.job_id, key) : client.retryJob(job.job_id, key)); if (projectRef.current) await refreshJobs(projectRef.current); }
    catch (cause) { showError(cause); } finally { setBusy(false); }
  }
  async function openAgentResult(result: AgentResultView, scope: AgentScope) {
    if (!canLeaveOutcomes()) return;
    const id = result.kind === 'project' ? result.resource_id : scope.scope_kind === 'project' ? scope.project_id : undefined;
    if (!id) { setPage('projects'); await loadProjects(); return; }
    await loadProjects(); await openProject(id, true);
    if (projectRef.current !== id) return;
    if (['evidence', 'note', 'export'].includes(result.kind)) {
      setOutcomeExport(result.kind === 'export' ? result.resource_id : undefined); setProjectPage('outcomes');
    } else if (['snapshot', 'query'].includes(result.kind)) setProjectPage('research');
    else setProjectPage('materials');
    setPage('projects');
  }
  return <main>
    <header><h1>{page === 'assistant' && auth ? '研究助手' : page === 'catalog' && auth ? '来源目录' : project?.name || '研究项目'}</h1><div className="actions"><button onClick={() => setTheme((theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) ? 'light' : 'dark')}>{theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches) ? '浅色' : '深色'}</button>{auth && <><span>{auth.actor.email}</span><button disabled={busy} onClick={() => void logout()}>退出</button></>}</div></header>
    {auth && <nav className="actions main-nav" aria-label="工作台"><button className={page === 'assistant' ? 'selected' : ''} disabled={busy} onClick={() => changePage('assistant')}>研究助手</button><button className={page === 'projects' ? 'selected' : ''} disabled={busy} onClick={() => changePage('projects')}>项目</button><button className={page === 'catalog' ? 'selected' : ''} disabled={busy} onClick={() => changePage('catalog')}>来源目录</button></nav>}
    {auth && <AgentWorkspace key={auth.actor.id} client={client} actorId={auth.actor.id} projects={projects} visible={page === 'assistant'} onOpenResult={(result, scope) => void openAgentResult(result, scope).catch(showError)} onUnauthorized={showError}/>}
    {auth && page === 'catalog' && <Catalog key={auth.actor.id} client={client} admin={auth.actor.is_platform_admin} onUnauthorized={showError}/>}
    {error && <p className="error" role="alert">{error}</p>}
    {restoring ? <p role="status">正在恢复登录状态…</p> : !auth ? <form className="login" onSubmit={event => void login(event)}><h2>登录</h2><label>邮箱<input name="email" type="email" autoComplete="username" required disabled={busy}/></label><label>密码<input name="password" type="password" autoComplete="current-password" required disabled={busy}/></label><button type="submit" disabled={busy}>{busy ? '登录中…' : '登录'}</button></form> : <div className="workspace" hidden={page !== 'projects'}>
      <aside><h2>项目</h2><nav aria-label="项目列表">{projects.map(item => <button className={project?.id === item.id ? 'selected' : ''} key={item.id} disabled={busy} onClick={() => void openProject(item.id)}>{item.name}<span>{roles[item.role]}</span></button>)}</nav>{projects.length === 0 && <p>暂无项目</p>}<form onSubmit={event => void createProject(event)}><label>新项目<input name="name" required maxLength={160} disabled={busy}/></label><button disabled={busy} type="submit">创建项目</button></form></aside>
      <section className="content">{!project ? <h2>选择或创建项目</h2> : <>
        <nav className="actions" aria-label="项目内容"><button className={projectPage === 'materials' ? 'selected' : ''} onClick={() => changeProjectPage('materials')}>项目材料</button><button className={projectPage === 'research' ? 'selected' : ''} onClick={() => changeProjectPage('research')}>语料检索</button><button className={projectPage === 'outcomes' ? 'selected' : ''} onClick={() => { setOutcomeExport(undefined); changeProjectPage('outcomes'); }}>笔记与成果</button></nav>
        {projectPage === 'outcomes' ? <Outcomes key={project.id} client={client} projectId={project.id} initialExportId={outcomeExport} leaveGuard={outcomeLeaveGuard} onUnauthorized={showError}/> : projectPage === 'research' ? <Research key={project.id} client={client} projectId={project.id} canSaveEvidence={project.permissions.upload} onExportCreated={id => { setOutcomeExport(id); setProjectPage('outcomes'); }} onUnauthorized={showError}/> : <>
        <ProjectSources key={project.id} client={client} projectId={project.id} onUnauthorized={showError}/>
        <div className="section-title"><h2>文件</h2><span>{roles[project.role]}</span></div>
        {project.permissions.upload ? <form onSubmit={event => void upload(event)}><label>选择文件<input ref={fileInput} type="file" accept=".txt,.csv,.tsv,.json,.jsonl" disabled={busy || !!pendingUpload} onChange={event => setFile(event.target.files?.[0])}/></label><div className="actions">{file && <span>{sizeLabel(file.size)}</span>}<button type="submit" disabled={busy || !file || !!pendingUpload}>上传并校验</button>{pendingUpload && <button type="button" disabled={busy} onClick={() => void retryComplete()}>重新提交校验</button>}</div>{uploadStage && <p role="status">{uploadStage}{uploadProgress !== null ? ` ${Math.round(uploadProgress * 100)}%` : '…'}</p>}</form> : <p>当前项目为只读</p>}
        <PrivateMaterials key={project.id} client={client} projectId={project.id} canWrite={project.permissions.upload} refreshToken={jobs.filter(job => job.kind === 'UPLOAD_VALIDATE' && job.state === 'SUCCEEDED').map(job => job.job_id).join(',')} onUnauthorized={showError}/><div className="section-title"><h2>上传校验任务</h2><button disabled={busy} onClick={() => void refreshJobs(project.id).catch(showError)}>刷新</button></div>
        {jobs.filter(job => job.kind === 'UPLOAD_VALIDATE').length === 0 ? <p>本页无上传校验任务</p> : <ul className="jobs">{jobs.filter(job => job.kind === 'UPLOAD_VALIDATE').map(job => <li key={job.job_id}><button className="job-open" onClick={() => setSelectedJob(job)}><strong>{job.filename}</strong><span>{stateNames[job.state]}</span><span>{sizeLabel(job.progress.processed_bytes)}{job.progress.total_bytes !== null ? ` / ${sizeLabel(job.progress.total_bytes)}` : ''}</span><time>{new Date(job.created_at).toLocaleString()}</time></button><div className="actions">{job.allowed_actions.map(action => <button key={action} disabled={busy} onClick={() => void jobAction(job, action)}>{action === 'cancel' ? '取消' : '重试'}</button>)}</div></li>)}</ul>}
        <div className="actions">{pageCursor.current && <button disabled={busy} onClick={() => { pageCursor.current = undefined; void refreshJobs(project.id).catch(showError); }}>返回最新任务</button>}{nextCursor && <button disabled={busy} onClick={() => void moreJobs()}>下一页任务</button>}</div>
        {selectedJob && <section className="detail"><h2>任务详情</h2><dl><div><dt>状态</dt><dd>{stateNames[selectedJob.state]}</dd></div><div><dt>执行次数</dt><dd>{selectedJob.attempt}</dd></div></dl>{selectedJob.error && <p role="alert">{selectedJob.error.message}（{selectedJob.error.code}）</p>}{selectedJob.result && selectedJob.result.state === 'VALIDATED' && <><p>文件大小、摘要和文本编码校验完成，尚未解析或建立检索索引。</p><dl><div><dt>文件大小</dt><dd>{sizeLabel(selectedJob.result.size)}</dd></div><div><dt>SHA-256</dt><dd className="digest">{selectedJob.result.sha256}</dd></div></dl></>}<details><summary>任务记录</summary><p className="digest">{selectedJob.job_id}</p></details></section>}
      </>}
      </>}</section>
    </div>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
