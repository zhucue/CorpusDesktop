import { useQuery } from "@tanstack/react-query";
import { Modal } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api, type KbDocument, type Page, type Scope, type Term } from "../../api";
import { knowledgeHref } from "../../features/knowledge/data";
import { listOf, useCorpora, useProjects, useSavedQueries, useSubcorpora } from "../../lib/data";
import { useDebounced } from "../../lib/useDebounced";
import { fmt } from "../../lib/format";
import { QueryChip } from "../common";
import { Icon, type IconName } from "../Icon";
import { kbDocIcon, kbIcon, pageIcon } from "../iconSets";
import { AGENT_TOOLS, TOOL_COUNT, TOOL_VIEW } from "./tools";

const TOOLS_GROUP = "助手工具";

interface Item {
  group: string;
  label: string;
  meta?: string;
  icon: IconName;
  query?: boolean;
  /** Keep the palette open after running (e.g. expanding a collapsed group). */
  keep?: boolean;
  /** Server-side match (文献 / 术语): shown without the local text filter. */
  remote?: boolean;
  run: () => void;
}

export function searchHref(projectId: string, query: string, scope?: unknown): string {
  const p = new URLSearchParams({ q: query });
  if (scope) p.set("scope", JSON.stringify(scope));
  return `/p/${projectId}/search?${p.toString()}`;
}

export function recentKey(projectId: string) {
  return `search-history:${projectId}`;
}

export default function CommandPalette({
  open,
  initial,
  projectId,
  onClose,
  scope,
  setScope,
}: {
  open: boolean;
  initial: string;
  projectId: string;
  onClose: () => void;
  /** The project's shared scope (lib/scope); picking a corpus here switches it for the current page too. */
  scope?: Scope | null;
  setScope: (s: Scope) => void;
}) {
  const navigate = useNavigate();
  const projects = useProjects();
  const corpora = useCorpora(projectId);
  const subcorpora = useSubcorpora(projectId);
  const queries = useSavedQueries(projectId);
  const [q, setQ] = useState(initial);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQ(initial);
      setActive(0);
      setTimeout(() => inputRef.current?.select(), 0);
    }
  }, [open, initial]);

  const go = (to: string) => () => navigate(to);
  const items: Item[] = useMemo(() => {
    const base = `/p/${projectId}`;
    const pages: Item[] = [
      { group: "页面", label: "语料库", icon: pageIcon.corpora, run: go(`${base}/corpora`) },
      { group: "页面", label: "检索", icon: pageIcon.search, run: go(`${base}/search`) },
      { group: "页面", label: "统计", icon: pageIcon.stats, run: go(`${base}/stats`) },
      { group: "页面", label: "标注", icon: pageIcon.annotate, run: go(`${base}/annotate`) },
      { group: "页面", label: "知识库", icon: pageIcon.knowledge, run: go(`${base}/knowledge`) },
      { group: "页面", label: "助手", icon: pageIcon.assistant, run: go(`${base}/assistant`) },
      { group: "页面", label: "任务", icon: pageIcon.jobs, run: go(`${base}/jobs`) },
      { group: "页面", label: "项目设置", icon: pageIcon.settings, run: go(`${base}/settings`) },
      { group: "页面", label: "打开引导", icon: "compass", run: go(`/onboarding?project=${projectId}`) },
    ];
    const proj: Item[] = (projects.data?.items ?? []).map((p) => ({
      group: "项目",
      label: p.name,
      meta: p.id === projectId ? "当前" : undefined,
      icon: "folder",
      run: go(`/p/${p.id}/corpora`),
    }));
    proj.push({ group: "项目", label: "新建项目", icon: "plus", run: go("/onboarding") });
    const current = (m: string, on: boolean) => (on ? `当前 · ${m}` : m);
    const corp: Item[] = (corpora.data?.items ?? []).map((c) => ({
      group: "语料库",
      label: c.name,
      meta: current(c.status === "ready" ? `${fmt(c.stats.tokens)} 词` : c.status, !!scope && "corpus_id" in scope && scope.corpus_id === c.id),
      icon: "library",
      run: () => setScope({ corpus_id: c.id }),
    }));
    const subs: Item[] = (subcorpora.data?.items ?? []).map((s) => ({
      group: "子库",
      label: s.name,
      meta: current(`${fmt(s.stats.tokens)} 词`, !!scope && "subcorpus_id" in scope && scope.subcorpus_id === s.id),
      icon: "filter",
      run: () => setScope({ subcorpus_id: s.id }),
    }));
    const saved: Item[] = (queries.data?.items ?? []).map((s) => ({
      group: "保存的查询",
      label: s.query,
      meta: s.name,
      icon: "bookmark",
      query: true,
      run: go(searchHref(projectId, s.query, s.scope)),
    }));
    // Chinese names; the English tool id stays in meta so typing it still finds the tool.
    const tools: Item[] = AGENT_TOOLS.flatMap((g) =>
      g.tools.map((t) => ({ group: TOOLS_GROUP, label: TOOL_VIEW[t]?.title ?? t, meta: `${g.group} · ${t}`, icon: TOOL_VIEW[t]?.icon ?? ("tool" as IconName), run: go(`${base}/assistant`) })),
    );
    return [...pages, ...proj, ...corp, ...subs, ...saved, ...tools];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, projects.data, corpora.data, subcorpora.data, queries.data, scope]);

  const needle = q.trim().toLowerCase();
  // Without a search the tools are collapsed into one entry that expands the group.
  const toolsCollapsed: Item = { group: TOOLS_GROUP, label: `展开全部 ${TOOL_COUNT} 个工具`, icon: "tool", keep: true, run: () => setQ(TOOLS_GROUP) };
  const kbQ = useDebounced(q.trim(), 250);
  const kbOn = open && kbQ.length > 0;
  const kbDocs = useQuery({
    queryKey: ["palette-kb-docs", projectId, kbQ],
    queryFn: async () => listOf(await api.get<KbDocument[] | Page<KbDocument>>(`/projects/${projectId}/kb/documents`, { q: kbQ, page_size: 8 })),
    enabled: kbOn,
    staleTime: 30_000,
    meta: { background: true },
  });
  const kbTerms = useQuery({
    queryKey: ["palette-kb-terms", projectId, kbQ],
    queryFn: async () => listOf(await api.get<Term[] | Page<Term>>(`/projects/${projectId}/kb/terms`, { q: kbQ, page_size: 8 })),
    enabled: kbOn,
    staleTime: 30_000,
    meta: { background: true },
  });
  const kindName: Record<string, string> = { literature: "文献", url: "网页", guideline: "规范", note: "笔记" };
  const remote: Item[] = kbOn
    ? [
        ...(kbDocs.data ?? []).slice(0, 8).map((d) => ({
          group: "文献",
          label: d.title,
          meta: kindName[d.kind] ?? d.kind,
          icon: kbDocIcon(d.kind, d.source, d.title),
          remote: true,
          run: go(knowledgeHref(projectId, { doc: d.id })),
        })),
        ...(kbTerms.data ?? []).slice(0, 8).map((t) => ({
          group: "术语",
          label: t.term,
          meta: t.translations?.[0]?.text ?? t.language,
          icon: kbIcon.term,
          remote: true,
          run: go(knowledgeHref(projectId, { tab: "terms", term: t.id, tq: t.term })),
        })),
      ]
    : [];
  const shown = [...(needle ? items.filter((it) => `${it.group} ${it.label} ${it.meta ?? ""}`.toLowerCase().includes(needle)) : [...items.filter((it) => it.group !== TOOLS_GROUP), toolsCollapsed]), ...remote];
  const groups: [string, { it: Item; idx: number }[]][] = [];
  shown.forEach((it, idx) => {
    let g = groups.find((x) => x[0] === it.group);
    if (!g) groups.push((g = [it.group, []]));
    g[1].push({ it, idx });
  });
  const current = Math.min(active, shown.length - 1);

  function pick(it: Item | undefined) {
    if (!it) return;
    if (it.keep) {
      it.run();
      setActive(0);
      return;
    }
    onClose();
    it.run();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab") {
      e.preventDefault();
      if (!shown.length) return;
      const up = e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey);
      const next = (current + (up ? -1 : 1) + shown.length) % shown.length;
      setActive(next);
      listRef.current?.querySelector(`#cmd-${next}`)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(shown[current]);
    }
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      width={640}
      style={{ top: "12vh" }}
      className="cmdk"
      destroyOnHidden
    >
      <div className="cmdk-in">
        <Icon name="search" size={18} />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
          placeholder="搜索页面、语料库、查询、文献、术语"
          aria-label="搜索"
          aria-controls="cmdk-list"
          aria-activedescendant={shown.length ? `cmd-${current}` : undefined}
          autoComplete="off"
          autoFocus
        />
        <kbd>Esc</kbd>
      </div>
      <div className="cmdk-list" id="cmdk-list" role="listbox" ref={listRef}>
        {shown.length === 0 && <div className="cmdk-empty">没有匹配“{q}”的结果</div>}
        {groups.map(([g, list]) => (
          <div key={g} role="group" aria-label={g}>
            <div className="cmdk-group">{g}</div>
            {list.map(({ it, idx }) => (
              <div
                key={idx}
                id={`cmd-${idx}`}
                role="option"
                aria-selected={idx === current}
                className={`cmdk-item ${idx === current ? "on" : ""}`}
                onMouseMove={() => setActive(idx)}
                onClick={() => pick(it)}
              >
                <Icon name={it.icon} />
                {it.query ? <QueryChip q={it.label} /> : <span>{it.label}</span>}
                {it.meta && <span className="meta">{it.meta}</span>}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="dlg-foot">
        <span>
          <kbd>↑</kbd> <kbd>↓</kbd> 选择
        </span>
        <span>
          <kbd>Enter</kbd> 打开
        </span>
        <span>
          <kbd>Esc</kbd> 关闭
        </span>
      </div>
    </Modal>
  );
}
