import { useIsFetching, useIsMutating, useQueryClient } from "@tanstack/react-query";
import { Dropdown, Spin, type MenuProps } from "antd";
import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api } from "../../api";
import { useCorpora, useMe, useProject, useProjectId, useProjects, useSubcorpora } from "../../lib/data";
import { useTheme } from "../../theme/theme";
import { Avatar, Monogram, Tip } from "../common";
import { ErrorBoundary } from "../common/ErrorBoundary";
import CommandPalette from "../global/CommandPalette";
import { EvidenceBasket, EvidenceProvider } from "../global/evidence";
import KeysOverlay from "../global/KeysOverlay";
import { TaskTray } from "../global/TaskTray";
import { Icon, type IconName } from "../Icon";
import { pageIcon } from "../iconSets";
import { FeedbackButton } from "./Feedback";
import { ShellProvider, useShell } from "./shell";

const AssistantDrawer = lazy(() => import("../../features/assistant/AssistantDrawer"));

const NAV: [string, string, IconName][] = [
  ["corpora", "语料库", pageIcon.corpora],
  ["search", "检索", pageIcon.search],
  ["stats", "统计", pageIcon.stats],
  ["annotate", "标注", pageIcon.annotate],
  ["knowledge", "知识库", pageIcon.knowledge],
  ["assistant", "助手", pageIcon.assistant],
  ["jobs", "任务", pageIcon.jobs],
];
const EVIDENCE_PAGES = ["search", "stats", "assistant", "annotate", "knowledge", "settings"];

export function usePageId(): string {
  return useLocation().pathname.split("/")[3] ?? "corpora";
}

function typing(t: EventTarget | null): boolean {
  return t instanceof HTMLElement && !!t.closest("input, textarea, select, [contenteditable='true']");
}

function NavList({ items, projectId }: { items: [string, string, IconName][]; projectId: string }) {
  const page = usePageId();
  const ref = useRef<HTMLElement>(null);
  const [ink, setInk] = useState<{ y: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const a = ref.current?.querySelector<HTMLAnchorElement>('a[aria-current="page"]');
    setInk(a ? { y: a.offsetTop, h: a.offsetHeight } : null);
  }, [page]);
  return (
    <nav className="nav" ref={ref} aria-label={items.length > 1 ? "主导航" : "设置"}>
      <span
        className="nav-ink"
        aria-hidden
        style={{ opacity: ink ? 1 : 0, transform: `translateY(${ink?.y ?? 0}px)`, height: ink?.h ?? 40 }}
      />
      {items.map(([key, label, icon]) => (
        <NavLink key={key} to={`/p/${projectId}/${key}`} aria-current={page === key ? "page" : undefined}>
          <Icon name={icon} size={18} />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function SideNav() {
  const projectId = useProjectId();
  const project = useProject();
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { openPalette } = useShell();
  const name = project.data?.name ?? "";
  const roleLabel = { owner: "负责人", editor: "编辑者", annotator: "标注者", viewer: "查看者" }[project.data?.role ?? "viewer"];

  async function logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      navigate("/login", { replace: true });
    }
  }

  return (
    <aside className="side">
      <Link className="brand" to={`/p/${projectId}/corpora`}>
        <span className="brand-mark">
          <Icon name="hash" />
        </span>
        语料研究平台
      </Link>
      <button className="btn project-switch" type="button" onClick={() => openPalette("项目")} aria-label="切换项目">
        <span className="row" style={{ gap: 8, minWidth: 0 }}>
          <Monogram name={name || "项目"} size="lg" />
          <span className="ellipsis">{name}</span>
        </span>
        <Icon name="down" size={14} />
      </button>
      <NavList items={NAV} projectId={projectId} />
      <div className="side-spacer" />
      <NavList items={[["settings", "设置", pageIcon.settings]]} projectId={projectId} />
      <div className="me">
        <Avatar name={me.data?.display_name || me.data?.email || "?"} />
        <div className="sm grow" style={{ minWidth: 0 }}>
          <div className="ellipsis" style={{ fontWeight: 500 }}>
            {me.data?.display_name || me.data?.email}
          </div>
          <div className="muted small">{roleLabel}</div>
        </div>
        <Tip title="退出登录">
          <button className="btn ghost icon" type="button" aria-label="退出登录" onClick={logout}>
            <Icon name="logout" />
          </button>
        </Tip>
      </div>
    </aside>
  );
}

type CrumbGroup = "项目" | "语料库" | "子库";
const NEW_PROJECT = "__new__";
const ANY_SUB = "__any__";

/** Menu entries of one breadcrumb segment: projects, the project's corpora, or the subcorpora of the corpus in scope. */
function useCrumbMenu(group: CrumbGroup): { items: MenuProps["items"]; selected: string[]; pick: (key: string) => void } {
  const { projectId, scopeInfo, setScope } = useShell();
  const projects = useProjects();
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const navigate = useNavigate();
  const page = usePageId();
  if (group === "项目")
    return {
      items: [
        ...(projects.data?.items ?? []).map((p) => ({ key: p.id, label: p.name, icon: <Icon name="folder" size={14} /> })),
        { type: "divider" as const },
        { key: NEW_PROJECT, label: "新建项目", icon: <Icon name="plus" size={14} /> },
      ],
      selected: [projectId],
      pick: (key) => {
        if (key === NEW_PROJECT) navigate("/onboarding");
        else if (key !== projectId) navigate(`/p/${key}/${NAV.some(([k]) => k === page) || page === "settings" || page === "help" ? page : "corpora"}`);
      },
    };
  if (group === "语料库")
    return {
      items: (corpora.data?.items ?? []).map((c) => ({
        key: c.id,
        label: c.project_id === null ? `${c.name}（内置）` : c.name,
        icon: <Icon name="library" size={14} />,
        disabled: c.status !== "ready" && c.status !== "stale",
      })),
      selected: scopeInfo.corpus ? [scopeInfo.corpus.id] : [],
      pick: (key) => setScope({ corpus_id: key }),
    };
  const corpusId = scopeInfo.corpus?.id;
  return {
    items: [
      { key: ANY_SUB, label: "不限子库" },
      ...(subs.data?.items ?? []).filter((s) => s.corpus_id === corpusId).map((s) => ({ key: s.id, label: s.name, icon: <Icon name="filter" size={14} /> })),
    ],
    selected: [scopeInfo.subcorpus?.id ?? ANY_SUB],
    pick: (key) => {
      if (key === ANY_SUB) {
        if (corpusId) setScope({ corpus_id: corpusId });
      } else setScope({ subcorpus_id: key });
    },
  };
}

function Crumb({ group, label, last, placeholder, mono }: { group: CrumbGroup; label: string; last: boolean; placeholder?: boolean; mono?: boolean }) {
  const menu = useCrumbMenu(group);
  return (
    <Dropdown
      trigger={["click"]}
      menu={{ items: menu.items, selectable: true, selectedKeys: menu.selected, onClick: ({ key }) => menu.pick(key), style: { maxHeight: 360, overflowY: "auto" } }}
    >
      <button type="button" className={`crumb ${last ? "last" : ""} ${placeholder ? "placeholder" : ""}`} aria-haspopup="menu" aria-label={`切换${group}：${label}`}>
        {mono && <Monogram name={label || "项目"} />}
        <span>{label}</span>
      </button>
    </Dropdown>
  );
}

/** Breadcrumb scope bar: 项目 › 语料库 › 子库; each segment opens a menu that switches it. */
export function ScopeCrumbs({ depth = 3 }: { depth?: 1 | 3 }) {
  const project = useProject();
  const { scopeInfo } = useShell();
  const name = project.data?.name ?? "";
  const segs: { label: string; group: CrumbGroup; placeholder?: boolean; mono?: boolean }[] = [{ label: name, group: "项目", mono: true }];
  if (depth === 3) {
    segs.push(scopeInfo.corpus ? { label: scopeInfo.corpus.name, group: "语料库" } : { label: "选择语料库", group: "语料库", placeholder: true });
    if (scopeInfo.subcorpus) segs.push({ label: scopeInfo.subcorpus.name, group: "子库" });
    else if (scopeInfo.corpus) segs.push({ label: "不限子库", group: "子库", placeholder: true });
  }
  return (
    <nav className="crumbs" aria-label="范围">
      {segs.map((s, i) => (
        <span key={s.group} className="row" style={{ gap: 2, minWidth: 0 }}>
          {i > 0 && <Icon name="right" className="sep" />}
          <Crumb group={s.group} label={s.label} last={i === segs.length - 1} placeholder={s.placeholder} mono={s.mono} />
        </span>
      ))}
    </nav>
  );
}

export function PageHeader({
  title,
  actions,
  crumbs = 3,
  busy,
}: {
  title: string;
  actions?: React.ReactNode;
  crumbs?: 0 | 1 | 3;
  busy?: boolean;
}) {
  const fetching = useIsFetching({ predicate: (q) => !q.meta?.background && q.state.fetchStatus === "fetching" });
  const mutating = useIsMutating();
  const { mode, toggle } = useTheme();
  const { projectId, openPalette, openKeys, assistantOpen, setAssistantOpen } = useShell();
  const page = usePageId();
  const [spun, setSpun] = useState(false);
  return (
    <header className={`topbar ${busy || fetching + mutating > 0 ? "busy" : ""}`}>
      <h1>{title}</h1>
      {crumbs > 0 && <ScopeCrumbs depth={crumbs === 1 ? 1 : 3} />}
      <div className="grow" />
      {actions && <div className="tb-actions">{actions}</div>}
      {page !== "assistant" && (
        <button className={`btn s ${assistantOpen ? "on" : "soft"}`} type="button" onClick={() => setAssistantOpen(!assistantOpen)} aria-pressed={assistantOpen}>
          <Icon name="spark" size={14} />
          助手
        </button>
      )}
      <div className="tb-tools">
        <button className="cmdk-trigger" type="button" onClick={() => openPalette("")} aria-label="打开命令面板">
          <Icon name="search" size={14} />
          <span className="grow">搜索或跳转</span>
          <kbd>Ctrl K</kbd>
        </button>
        <FeedbackButton />
        <Tip title="帮助">
          <Link className={`btn ghost icon ${page === "help" ? "on" : ""}`} to={`/p/${projectId}/help`} aria-label="帮助">
            <Icon name="bookopen" />
          </Link>
        </Tip>
        <Tip title="快捷键（?）">
          <button className="btn ghost icon" type="button" aria-label="快捷键" onClick={openKeys}>
            <Icon name="keyboard" />
          </button>
        </Tip>
        <Tip title="深色 / 浅色">
          <button
            className={`btn ghost icon theme-btn ${spun ? "spin-once" : ""}`}
            type="button"
            aria-label="切换深色模式"
            onClick={() => {
              toggle();
              setSpun((s) => !s);
            }}
          >
            <Icon name={mode === "dark" ? "moon" : "sun"} />
          </button>
        </Tip>
      </div>
      <div className="topbar-prog" aria-hidden />
    </header>
  );
}

function ShellFrame() {
  const projectId = useProjectId();
  const page = usePageId();
  const loc = useLocation();
  const shell = useShell();
  const [panel, setPanel] = useState<"tray" | "ev" | null>(null);

  useEffect(() => {
    if (!panel) return;
    const close = (e: MouseEvent) => {
      if (!(e.target instanceof HTMLElement) || !e.target.closest(".dock")) setPanel(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [panel]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPanel(null);
      if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/") {
        const f = document.querySelector<HTMLElement>("[data-slash]");
        if (f) {
          e.preventDefault();
          f.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={`app ${shell.assistantOpen && page !== "assistant" ? "has-asst" : ""}`}>
      <SideNav />
      <main className="main">
        <ErrorBoundary key={loc.pathname}>
          <Suspense fallback={<Spin style={{ margin: 80 }} />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
      {shell.assistantOpen && page !== "assistant" && (
        <Suspense fallback={null}>
          <AssistantDrawer onClose={() => shell.setAssistantOpen(false)} />
        </Suspense>
      )}
      <div className="dock">
        <TaskTray projectId={projectId} open={panel === "tray"} onToggle={() => setPanel(panel === "tray" ? null : "tray")} />
        {EVIDENCE_PAGES.includes(page) && (
          <EvidenceBasket projectId={projectId} open={panel === "ev"} onToggle={() => setPanel(panel === "ev" ? null : "ev")} />
        )}
      </div>
    </div>
  );
}

export default function AppShell() {
  const projectId = useProjectId();
  const page = usePageId();
  const [palette, setPalette] = useState<{ open: boolean; q: string }>({ open: false, q: "" });
  const [keys, setKeys] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem("last-project", projectId);
    } catch {
      /* storage unavailable */
    }
  }, [projectId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setKeys(false);
        setPalette((p) => ({ open: !p.open, q: "" }));
        return;
      }
      if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "?") {
        e.preventDefault();
        setKeys((k) => !k);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <ShellProvider projectId={projectId} openPalette={(q = "") => setPalette({ open: true, q })} openKeys={() => setKeys(true)}>
      <EvidenceProvider projectId={projectId}>
        <ShellFrame />
        <PaletteHost open={palette.open} q={palette.q} onClose={() => setPalette({ open: false, q: "" })} />
        <KeysOverlay open={keys} page={page} onClose={() => setKeys(false)} />
      </EvidenceProvider>
    </ShellProvider>
  );
}

function PaletteHost({ open, q, onClose }: { open: boolean; q: string; onClose: () => void }) {
  const { projectId, scope, setScope } = useShell();
  return <CommandPalette open={open} initial={q} projectId={projectId} onClose={onClose} scope={scope} setScope={setScope} />;
}
