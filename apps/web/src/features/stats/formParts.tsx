import { Form } from "antd";
import type { Scope } from "../../api";
import { Icon } from "../../components/Icon";

export type Body = Record<string, unknown>;

export const POS_OPTIONS = [
  ["NOUN", "名词"],
  ["VERB", "动词"],
  ["ADJ", "形容词"],
  ["ADV", "副词"],
  ["PRON", "代词"],
  ["ADP", "介词"],
  ["NUM", "数词"],
  ["PROPN", "专名"],
].map(([v, l]) => ({ value: v, label: `${l} ${v}` }));

export const fieldLabel = (f: string) => (f === "year" ? "年份 year" : f);

export function scopeRule(msg = "请选择范围") {
  return [{ required: true, message: msg }];
}

/** Stored scopes carry nulls and a display name; the form wants a request scope. */
export function toScope(v: unknown): Scope | undefined {
  const s = (v ?? {}) as { corpus_id?: string | null; subcorpus_id?: string | null; filter?: Record<string, unknown> | null };
  if (s.subcorpus_id) return { subcorpus_id: s.subcorpus_id };
  if (s.corpus_id && s.filter) return { corpus_id: s.corpus_id, filter: s.filter } as unknown as Scope;
  if (s.corpus_id) return { corpus_id: s.corpus_id };
  return undefined;
}

export function ParamsCard({
  children,
  onSubmit,
  running,
  blocked,
  form,
}: {
  children: React.ReactNode;
  onSubmit: () => void;
  running: boolean;
  /** The range does not suit the method (译法 on a non-parallel corpus). */
  blocked?: boolean;
  form: ReturnType<typeof Form.useForm>[0];
}) {
  return (
    <Form form={form} className="card params" layout="vertical" onFinish={onSubmit} requiredMark={false}>
      <div className="params-fields">{children}</div>
      <button className="btn p params-run" type="submit" disabled={running || blocked}>
        {running ? <span className="spin" /> : <Icon name="play" size={14} />}
        计算
      </button>
    </Form>
  );
}
