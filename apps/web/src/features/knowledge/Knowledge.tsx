import { useLayoutEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { kbIcon } from "../../components/iconSets";
import { PageHeader } from "../../components/shell/AppShell";
import { canEdit, useProject, useProjectId } from "../../lib/data";
import { fmt } from "../../lib/format";
import { useKbDocument, useKbDocuments, useTerms, type KbTab } from "./data";
import GuidelinesTab from "./Guidelines";
import KbSearch from "./KbSearch";
import { DocDrawer, DocTable, ImportCard } from "./Literature";
import NotesTab from "./Notes";
import TermsTab, { useTermExport } from "./Terms";
import "./knowledge.css";

const TABS: [KbTab, string, IconName][] = [
  ["lit", "文献", kbIcon.literature],
  ["terms", "术语", kbIcon.term],
  ["guides", "规范", kbIcon.guideline],
  ["notes", "笔记", kbIcon.note],
];

export default function Knowledge() {
  const projectId = useProjectId();
  const project = useProject();
  const editable = canEdit(project.data);
  const canWriteNotes = !!project.data && project.data.role !== "viewer";
  const [params, setParams] = useSearchParams();
  const docs = useKbDocuments(projectId);
  const all = docs.data ?? [];
  const termCount = useTerms(projectId, { page: 1, page_size: 1 });
  const exportTerms = useTermExport(projectId);

  const docParam = params.get("doc");
  const listed = docParam ? all.find((d) => d.id === docParam) : undefined;
  const fetched = useKbDocument(docParam && docs.isSuccess && !listed ? docParam : null);
  const target = listed ?? fetched.data;
  const docTab: KbTab | null = target ? (target.kind === "note" ? "notes" : target.kind === "guideline" ? "guides" : "lit") : null;
  const tab = (params.get("tab") as KbTab | null) ?? docTab ?? "lit";

  const set = (p: Record<string, string | null>) =>
    setParams(
      (old) => {
        const n = new URLSearchParams(old);
        for (const [k, v] of Object.entries(p)) if (v) n.set(k, v);
        else n.delete(k);
        return n;
      },
      { replace: false },
    );

  const counts: Record<KbTab, number> = {
    lit: all.filter((d) => d.kind === "literature" || d.kind === "url").length,
    terms: termCount.data?.total ?? 0,
    guides: all.filter((d) => d.kind === "guideline").length,
    notes: all.filter((d) => d.kind === "note").length,
  };

  // Sliding ink under the selected tab.
  const tabsRef = useRef<HTMLDivElement>(null);
  const [ink, setInk] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const b = tabsRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]');
    setInk(b ? { x: b.offsetLeft, w: b.offsetWidth } : null);
  }, [tab, counts.lit, counts.terms, counts.guides, counts.notes]);

  function goImport() {
    set({ tab: "lit", doc: null, chunk: null });
    setTimeout(() => {
      const el = document.getElementById("kb-import");
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      el?.animate?.([{ boxShadow: "0 0 0 0 rgba(21, 112, 239,.4)" }, { boxShadow: "0 0 0 8px rgba(21, 112, 239,0)" }], { duration: 700 });
    }, 50);
  }

  return (
    <>
      <PageHeader
        title="知识库"
        crumbs={1}
        actions={
          <>
            <button className="btn s" type="button" disabled={exportTerms.isPending} onClick={() => exportTerms.mutate("tbx")}>
              <Icon name="download" size={14} />
              <span className="lbl">导出术语表</span>
            </button>
            {editable && (
              <button className="btn s p" type="button" onClick={goImport}>
                <Icon name="upload" size={14} />
                <span className="lbl">导入</span>
              </button>
            )}
          </>
        }
      />
      <div className="content kb">
        <KbSearch projectId={projectId} />
        <div className="tabs" role="tablist" aria-label="分区" ref={tabsRef}>
          {TABS.map(([k, label, icon]) => (
            <button
              key={k}
              role="tab"
              type="button"
              aria-selected={tab === k}
              aria-controls={`kb-p-${k}`}
              onClick={() => set({ tab: k, doc: null, chunk: null, term: null, tq: null })}
            >
              <Icon name={icon} size={14} /> {label} <span className="num muted small">{fmt(counts[k])}</span>
            </button>
          ))}
          <span className="tab-ink" aria-hidden style={{ transform: `translateX(${ink?.x ?? 0}px)`, width: ink?.w ?? 0 }} />
        </div>

        {tab === "lit" && (
          <section role="tabpanel" id="kb-p-lit" className="kb-grid">
            <ImportCard projectId={projectId} docs={all} editable={editable} />
            <DocTable docs={all} loading={docs.isPending} error={docs.error} onOpen={(id) => set({ doc: id, chunk: null })} />
          </section>
        )}
        {tab === "terms" && (
          <div role="tabpanel" id="kb-p-terms">
            <TermsTab
              projectId={projectId}
              editable={editable}
              docs={all}
              openTermId={params.get("term")}
              initialQ={params.get("tq") ?? ""}
              onOpenTerm={(id) => set({ tab: "terms", term: id })}
            />
          </div>
        )}
        {tab === "guides" && (
          <div role="tabpanel" id="kb-p-guides">
            <GuidelinesTab projectId={projectId} docs={all} editable={editable} selected={docTab === "guides" ? docParam : null} onSelect={(id) => set({ tab: "guides", doc: id, chunk: null })} />
          </div>
        )}
        {tab === "notes" && (
          <div role="tabpanel" id="kb-p-notes">
            <NotesTab projectId={projectId} docs={all} editable={canWriteNotes} selected={docTab === "notes" ? docParam : null} onSelect={(id) => set({ tab: "notes", doc: id, chunk: null })} />
          </div>
        )}
      </div>
      <DocDrawer
        docId={docTab === "lit" ? docParam : null}
        chunkId={params.get("chunk")}
        editable={editable}
        onClose={() => set({ doc: null, chunk: null })}
        onOpenGuideline={(id) => set({ tab: "guides", doc: id, chunk: null })}
      />
    </>
  );
}
