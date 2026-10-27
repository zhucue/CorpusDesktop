import { Modal } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { Scope } from "../../api";
import { useCorpora, useProjects, useSavedQueries, useSubcorpora } from "../../lib/data";
import { fmt } from "../../lib/format";
import { QueryChip } from "../common";
import { Icon, type IconName } from "../Icon";
import { AGENT_TOOLS } from "./tools";

interface Item {
  group: string;
  label: string;
  meta?: string;
  icon: IconName;
  query?: boolean;
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
  setScope,
}: {
  open: boolean;
  initial: string;
  projectId: string;
  onClose: () => void;
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
      { group: "页面", label: "语料库", icon: "db", run: go(`${base}/corpora`) },
      { group: "页面", label: "检索", icon: "search", run: go(`${base}/search`) },
      { group: "页面", label: "统计", icon: "chart", run: go(`${base}/stats`) },
      { group: "页面", label: "助手", icon: "spark", run: go(`${base}/assistant`) },
      { group: "页面", label: "任务", icon: "clock", run: go(`${base}/jobs`) },
      { group: "页面", label: "项目设置", icon: "sliders", run: go(`${base}/settings`) },
      { group: "页面", label: "打开引导", icon: "compass", run: go(`/onboarding?project=${projectId}`) },
    ];
    const proj: Item[] = (projects.data?.items ?? []).map((p) => ({
      group: "项目",
      label: p.name,
      meta: p.id === projectId ? "当前" : undefined,
      icon: "folder",
      run: go(`/p/${p.id}/corpora`),
    }));
    const corp: Item[] = (corpora.data?.items ?? []).map((c) => ({
      group: "语料库",
      label: c.name,
      meta: c.status === "ready" ? `${fmt(c.stats.tokens)} 词` : c.status,
      icon: "db",
      run: () => setScope({ corpus_id: c.id }),
    }));
    const subs: Item[] = (subcorpora.data?.items ?? []).map((s) => ({
      group: "子库",
      label: s.name,
      meta: `${fmt(s.stats.tokens)} 词`,
      icon: "filter",
      run: () => setScope({ subcorpus_id: s.id }),
    }));
    const saved: Item[] = (queries.data?.items ?? []).map((s) => ({
      group: "保存的查询",
      label: s.query,
      meta: s.name,
      icon: "search",
      query: true,
      run: go(searchHref(projectId, s.query, s.scope)),
    }));
    const tools: Item[] = AGENT_TOOLS.flatMap((g) =>
      g.tools.map((t) => ({ group: "助手工具", label: t, meta: g.group, icon: "tool" as IconName, run: go(`${base}/assistant`) })),
    );
    return [...pages, ...proj, ...corp, ...subs, ...saved, ...tools];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, projects.data, corpora.data, subcorpora.data, queries.data]);

  const needle = q.trim().toLowerCase();
  const shown = needle ? items.filter((it) => `${it.group} ${it.label} ${it.meta ?? ""}`.toLowerCase().includes(needle)) : items;
  const groups: [string, { it: Item; idx: number }[]][] = [];
  shown.forEach((it, idx) => {
    let g = groups.find((x) => x[0] === it.group);
    if (!g) groups.push((g = [it.group, []]));
    g[1].push({ it, idx });
  });
  const current = Math.min(active, shown.length - 1);

  function pick(it: Item | undefined) {
    if (!it) return;
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
          placeholder="搜索页面、语料库、查询、工具"
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
