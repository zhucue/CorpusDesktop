import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Dropdown, Form, Input, InputNumber, Modal, Select } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, errorText, type AlignedCondition, type BreakdownBy, type Job, type LabelSet, type ParseResult, type SearchRequest, type SearchScope } from "../../api";
import { ErrorAlert, Tip } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useJob, useJobCreated } from "../../lib/data";
import { useDebounced } from "../../lib/useDebounced";
import { useLabelSets } from "../annotate/data";
import { fieldLabel } from "./fields";

/* ---------- 译文条件 (contracts/p8.md §四) ---------- */

/** ?aligned=<JSON {op, query}> from stats rows and assistant links; null when missing or malformed. */
export function parseAlignedParam(s: string | null): AlignedCondition | null {
  if (!s) return null;
  try {
    const v = JSON.parse(s) as Partial<AlignedCondition>;
    return (v.op === "+" || v.op === "-") && typeof v.query === "string" && v.query.trim() ? { op: v.op, query: v.query } : null;
  } catch {
    return null;
  }
}

/** Errors of /search that belong to the translation condition input (the API prefixes them with 译文条件). */
export function isAlignedError(e: unknown): boolean {
  return e instanceof Error && e.message.includes("译文条件");
}

/** 含 / 不含 + query: parsed as you type against the searched corpus; errors point at the character. */
export function AlignedInput({
  op,
  query,
  onOp,
  onQuery,
  scope,
  error,
  onSubmit,
}: {
  op: "+" | "-";
  query: string;
  onOp: (op: "+" | "-") => void;
  onQuery: (q: string) => void;
  scope: SearchScope | null;
  error: unknown;
  onSubmit: () => void;
}) {
  const q = useDebounced(query.trim(), 300);
  const parse = useQuery({
    queryKey: ["parse", q, scope ? JSON.stringify(scope) : ""],
    queryFn: () => api.post<ParseResult>("/search/parse", scope ? { query: q, scope } : { query: q }),
    enabled: q.length > 0,
    staleTime: Infinity,
    meta: { background: true },
  });
  const shown = q && q === query.trim() ? parse.data : undefined;
  const bad = shown && !shown.ok && shown.error ? shown.error : null;
  return (
    <div className="col gap-4">
      <div className="row" style={{ gap: 8 }}>
        <span className="small muted">译文条件</span>
        <Select
          size="small"
          value={op}
          onChange={onOp}
          style={{ width: 76 }}
          aria-label="译文条件方式"
          options={[
            { value: "+", label: "含" },
            { value: "-", label: "不含" },
          ]}
        />
        <Input
          size="small"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          onPressEnter={onSubmit}
          placeholder="对齐句中的查询式，如 translate"
          status={bad || error ? "error" : undefined}
          aria-label="译文条件查询式"
          allowClear
          style={{ maxWidth: 360 }}
        />
      </div>
      {bad ? (
        <span className="small bad" role="alert">
          <Icon name="alert" size={14} />第 {bad.position + 1} 个字符：{bad.message}
        </span>
      ) : error ? (
        <span className="small bad" role="alert">
          {errorText(error)}
        </span>
      ) : null}
    </div>
  );
}

/* ---------- 分解 / 统计译法: start a statistic and open its result on the stats page ---------- */

/** POST /stats/{method}, wait for the job, then go to /stats?stat=<id>. */
function useStatLaunch(projectId: string) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const jobCreated = useJobCreated();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const start = useMutation({
    mutationFn: ({ method, body }: { method: string; body: object }) => api.post<Job>(`/stats/${method}`, body),
    onSuccess: (j) => {
      setJobId(j.id);
      jobCreated(projectId);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const state = job.data?.state;
  useEffect(() => {
    if (!jobId || !job.data) return;
    if (state === "succeeded" && job.data.result?.stat_id) {
      setJobId(null);
      navigate(`/p/${projectId}/stats?stat=${job.data.result.stat_id}`);
    } else if (state === "failed" || state === "cancelled") {
      setJobId(null);
      message.error(job.data.error?.message ?? "统计失败");
    }
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  const busy = start.isPending || (!!jobId && (state === undefined || state === "queued" || state === "running"));
  return { busy, run: (method: string, body: object) => start.mutate({ method, body }) };
}

const BREAKDOWN: [BreakdownBy, string][] = [
  ["word", "按词形"],
  ["lemma", "按词元"],
  ["pos", "按词性"],
  ["left1", "按左一词"],
  ["right1", "按右一词"],
];

/** Statistics from the result bar count the hits without a translation condition: disabled while one is set. */
const ALIGNED_OFF = "含译文条件时不可用";

export function BreakdownMenu({ projectId, req, fields }: { projectId: string; req: SearchRequest | null; fields: string[] }) {
  const launch = useStatLaunch(projectId);
  const off = !req || launch.busy || !!req.aligned;
  const items = [
    ...BREAKDOWN.map(([k, label]) => ({ key: k, label })),
    ...(fields.filter((f) => f !== "position").length
      ? [
          { type: "divider" as const },
          ...fields.filter((f) => f !== "position").map((f) => ({ key: `meta:${f}`, label: `按${fieldLabel(f)}` })),
        ]
      : []),
  ];
  return (
    <Dropdown
      trigger={["click"]}
      disabled={off}
      menu={{
        items,
        onClick: ({ key }) =>
          req &&
          launch.run("breakdown", {
            project_id: projectId,
            scope: req.scope,
            query: req.query,
            by: key,
            top: 200,
            min_freq: 1,
            ...(req.layers ? { layers: req.layers } : {}),
          }),
      }}
    >
      <button className="btn s" type="button" disabled={off} title={req?.aligned ? ALIGNED_OFF : "命中频次分解，结果在统计页"}>
        {launch.busy ? <span className="spin" /> : <Icon name="table" size={14} />}
        分解
        <Icon name="down" size={14} />
      </button>
    </Dropdown>
  );
}

export function TranslationsButton({ projectId, req }: { projectId: string; req: SearchRequest | null }) {
  const launch = useStatLaunch(projectId);
  return (
    <Tip title={req?.aligned ? ALIGNED_OFF : "对齐句中的译文词，结果在统计页"}>
      <button
        className="btn s"
        type="button"
        disabled={!req || launch.busy || !!req.aligned}
        onClick={() =>
          req &&
          launch.run("translations", {
            project_id: projectId,
            scope: req.scope,
            query: req.query,
            unit: "word",
            measure: "dice",
            top: 100,
            min_freq: 2,
            exclude_punct: true,
            ...(req.layers ? { layers: req.layers } : {}),
          })
        }
      >
        {launch.busy ? <span className="spin" /> : <Icon name="align" size={14} />}
        统计译法
      </button>
    </Tip>
  );
}

/* ---------- 抽样编码 (contracts/p8.md §五) ---------- */

interface SampleResult {
  layer_id: string;
  sampled: number;
  total: number;
  seed: number;
}

/** Label ids from names: whitespace removed, repeats numbered. */
export function labelsFromText(text: string): { id: string; name: string }[] {
  const out: { id: string; name: string }[] = [];
  const used = new Set<string>();
  for (const raw of text.split(/[\n,，、]/)) {
    const name = raw.trim();
    if (!name) continue;
    let id = name.replace(/\s+/g, "_").slice(0, 60);
    for (let k = 2; used.has(id); k++) id = `${name.replace(/\s+/g, "_").slice(0, 56)}_${k}`;
    used.add(id);
    out.push({ id, name: name.slice(0, 100) });
  }
  return out;
}

type SampleForm = { n: number; seed?: number | null; label_set_id?: string; new_set_name?: string; new_labels?: string; name: string };

export function SampleDialog({
  open,
  onClose,
  projectId,
  req,
  hits,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  req: SearchRequest | null;
  hits: number | null;
}) {
  const [form] = Form.useForm<SampleForm>();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const labelSets = useLabelSets(projectId);
  const spanSets = (labelSets.data ?? []).filter((s) => s.kind === "span");
  const [newSet, setNewSet] = useState(false);
  const create = useMutation({
    mutationFn: async (v: SampleForm) => {
      let setId = v.label_set_id;
      if (newSet) {
        const labels = labelsFromText(v.new_labels ?? "");
        const s = await api.post<LabelSet>(`/projects/${projectId}/label-sets`, { name: (v.new_set_name ?? "").trim(), kind: "span", labels });
        qc.invalidateQueries({ queryKey: ["label-sets", projectId] });
        setId = s.id;
      }
      return api.post<SampleResult>(`/projects/${projectId}/samples`, {
        scope: req!.scope,
        query: req!.query,
        ...(req!.aligned ? { aligned: req!.aligned } : {}),
        ...(req!.layers ? { layers: req!.layers } : {}),
        n: v.n,
        ...(v.seed != null ? { seed: v.seed } : {}),
        layer: { name: v.name.trim(), label_set_id: setId },
      });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["layers", projectId] });
      message.success(`已抽取 ${r.sampled} 条（共 ${r.total} 条命中，seed ${r.seed}）`);
      onClose();
      navigate(`/p/${projectId}/annotate?layer=${r.layer_id}`);
    },
  });
  return (
    <Modal title="抽样编码" open={open} footer={null} onCancel={onClose} destroyOnHidden>
      {req && (
        <Form<SampleForm>
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{ n: Math.min(100, hits ?? 100), name: `抽样 · ${req.query}`.slice(0, 200) }}
          onFinish={(v) => create.mutate(v)}
        >
          <div className="small muted" style={{ marginBottom: 12 }}>
            {req.query}
            {req.aligned ? ` · 译文${req.aligned.op === "+" ? "含" : "不含"} ${req.aligned.query}` : ""}
            {hits != null ? ` · ${hits} 条命中` : ""}
          </div>
          <div className="row" style={{ gap: 12 }}>
            <Form.Item name="n" label="抽取条数" rules={[{ required: true, message: "请输入条数" }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={500} precision={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="seed" label="随机种子" style={{ flex: 1 }}>
              <InputNumber min={0} max={2147483647} precision={0} placeholder="随机" style={{ width: "100%" }} />
            </Form.Item>
          </div>
          {newSet ? (
            <>
              <Form.Item name="new_set_name" label="新标签集名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
                <Input maxLength={200} />
              </Form.Item>
              <Form.Item
                name="new_labels"
                label="标签（每行一个，或用逗号分隔）"
                rules={[{ validator: (_, v) => (labelsFromText(v ?? "").length ? Promise.resolve() : Promise.reject(new Error("至少一个标签"))) }]}
              >
                <Input.TextArea rows={3} placeholder={"字面\n比喻"} />
              </Form.Item>
              <button className="btn xs ghost" type="button" style={{ marginBottom: 12 }} onClick={() => setNewSet(false)}>
                选择已有标签集
              </button>
            </>
          ) : (
            <Form.Item label="标签集" required>
              <div className="row" style={{ gap: 8 }}>
                <Form.Item name="label_set_id" noStyle rules={[{ required: true, message: "请选择标签集" }]}>
                  <Select
                    loading={labelSets.isPending}
                    options={spanSets.map((s) => ({ value: s.id, label: s.name }))}
                    placeholder="片段标签集"
                    style={{ flex: 1 }}
                    aria-label="标签集"
                  />
                </Form.Item>
                <button className="btn s" type="button" onClick={() => setNewSet(true)}>
                  <Icon name="plus" size={14} />
                  新建
                </button>
              </div>
            </Form.Item>
          )}
          <Form.Item name="name" label="层名" rules={[{ required: true, whitespace: true, message: "请输入层名" }]}>
            <Input maxLength={200} />
          </Form.Item>
          <ErrorAlert error={create.error ?? labelSets.error} style={{ marginBottom: 12 }} />
          <button className="btn p" type="submit" disabled={create.isPending}>
            {create.isPending && <span className="spin" />}
            抽样并开始编码
          </button>
        </Form>
      )}
    </Modal>
  );
}
