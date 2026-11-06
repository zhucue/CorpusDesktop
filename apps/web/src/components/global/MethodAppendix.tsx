import { useQuery } from "@tanstack/react-query";
import { App, Modal, Radio, Spin } from "antd";
import { useState } from "react";
import { Link } from "react-router";
import { api, buildInit, errorFromResponse } from "../../api";
import { knowledgeHref } from "../../features/knowledge/data";
import { NotePicker, writeToNote, type NoteTarget } from "../../features/knowledge/NotePicker";
import { ErrorAlert } from "../common";
import { Markdown } from "../common/Markdown";
import { Icon } from "../Icon";

/** 方法附录对话框（contracts/p8.md 第六节）：预览、复制、下载 DOCX、保存为笔记。 */
export interface MethodAppendixSearch {
  query: string;
  scope: Record<string, unknown>;
  aligned?: { op: "+" | "-"; query: string } | null;
}

export interface MethodAppendixProps {
  projectId: string;
  statIds?: string[];
  searches?: MethodAppendixSearch[];
  layerIds?: string[];
  evidence?: boolean;
  onClose: () => void;
}

export type CitationStyle = "gbt7714" | "apa";

export interface MethodAppendixResult {
  markdown: string;
  citations: string[];
}

export function appendixBody(p: Pick<MethodAppendixProps, "statIds" | "searches" | "layerIds" | "evidence">, style: CitationStyle) {
  return {
    stat_ids: p.statIds ?? [],
    searches: p.searches ?? [],
    layer_ids: p.layerIds ?? [],
    evidence: !!p.evidence,
    style,
  };
}

function filenameOf(res: Response): string {
  const cd = res.headers.get("Content-Disposition") ?? "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  return m ? decodeURIComponent(m[1]) : "方法附录.docx";
}

async function downloadDocx(projectId: string, body: ReturnType<typeof appendixBody>) {
  const res = await fetch(`/api/projects/${projectId}/method-appendix?format=docx`, buildInit("POST", body));
  if (!res.ok) throw await errorFromResponse(res, "POST");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameOf(res);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function MethodAppendix({ projectId, statIds, searches, layerIds, evidence, onClose }: MethodAppendixProps) {
  const { message } = App.useApp();
  const [style, setStyle] = useState<CitationStyle>("gbt7714");
  const [picking, setPicking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const body = appendixBody({ statIds, searches, layerIds, evidence }, style);
  const result = useQuery({
    queryKey: ["method-appendix", projectId, body],
    queryFn: () => api.post<MethodAppendixResult>(`/projects/${projectId}/method-appendix`, body),
    staleTime: 60_000,
  });
  const markdown = result.data?.markdown ?? "";

  async function copy() {
    try {
      await navigator.clipboard.writeText(markdown);
      message.success("已复制 Markdown");
    } catch {
      message.error("复制失败，请手动选择文本");
    }
  }

  async function download() {
    setDownloading(true);
    try {
      await downloadDocx(projectId, body);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(false);
    }
  }

  async function toNote(t: NoteTarget) {
    const note = await writeToNote(projectId, t, markdown);
    message.success(
      <span>
        已保存到笔记「{note.title}」，<Link to={knowledgeHref(projectId, { tab: "notes", doc: note.id })}>打开笔记</Link>
      </span>,
    );
  }

  const ready = result.isSuccess && !!markdown;
  return (
    <>
      <Modal
        title="方法附录"
        open
        onCancel={onClose}
        width={760}
        destroyOnHidden
        footer={
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <button className="btn" type="button" disabled={!ready} onClick={() => void copy()}>
              <Icon name="copy" size={14} />
              复制
            </button>
            <button className="btn" type="button" disabled={!ready || downloading} onClick={() => void download()}>
              <Icon name="download" size={14} />
              下载 DOCX
            </button>
            <button className="btn" type="button" disabled={!ready} onClick={() => setPicking(true)}>
              <Icon name="note" size={14} />
              保存为笔记
            </button>
            <button className="btn" type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        }
      >
        <div className="col" style={{ gap: 12 }}>
          <Radio.Group value={style} onChange={(e) => setStyle(e.target.value)} aria-label="引用格式" size="small">
            <Radio.Button value="gbt7714">GB/T 7714</Radio.Button>
            <Radio.Button value="apa">APA</Radio.Button>
          </Radio.Group>
          {result.isPending ? (
            <div className="row" style={{ justifyContent: "center", padding: 32 }}>
              <Spin />
              <span className="muted">生成中</span>
            </div>
          ) : result.isError ? (
            <ErrorAlert error={result.error}>
              <button className="btn xs" type="button" onClick={() => void result.refetch()}>
                重试
              </button>
            </ErrorAlert>
          ) : (
            <div style={{ maxHeight: "60vh", overflow: "auto" }} data-testid="method-appendix-preview">
              <Markdown text={markdown} />
            </div>
          )}
        </div>
      </Modal>
      <NotePicker open={picking} projectId={projectId} title="保存为笔记" defaultTitle="方法附录" onClose={() => setPicking(false)} onPick={toNote} />
    </>
  );
}

export default MethodAppendix;
