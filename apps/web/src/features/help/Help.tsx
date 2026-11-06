import { useQuery } from "@tanstack/react-query";
import { App, Segmented } from "antd";
import { Fragment, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { api } from "../../api";
import { ErrorAlert, QueryChip, Skeleton, Tip } from "../../components/common";
import { searchHref } from "../../components/global/CommandPalette";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import {
  ERROR_ROWS,
  FORMAT_ROWS,
  IMPORT_LIMITS,
  MAPPING_ROWS,
  METRIC_GROUPS,
  METRIC_NOTES,
  PRIVACY_ROWS,
  QUERY_NOTES,
  QUERY_ROWS,
  ROLE_ROWS,
  SECTIONS,
} from "./content";
import "./help.css";

type Style = "gbt7714" | "apa";

export interface HelpMetric {
  key: string;
  name: string;
  formula: string;
  references: { key: string; label: string; text: string }[];
}

export function useHelpMetrics(style: Style) {
  return useQuery({
    queryKey: ["help-metrics", style],
    queryFn: () => api.get<{ style: Style; items: HelpMetric[] }>("/help/metrics", { style }),
    staleTime: Infinity,
  });
}

function KvTable({ rows, head }: { rows: [string, string][]; head?: [string, string] }) {
  return (
    <table className="tbl help-tbl">
      {head && (
        <thead>
          <tr>
            <th>{head[0]}</th>
            <th>{head[1]}</th>
          </tr>
        </thead>
      )}
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Example({ q, projectId }: { q: string; projectId?: string }) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  return (
    <span className="help-ex">
      <QueryChip q={q} />
      <Tip title="复制">
        <button
          type="button"
          className="btn ghost icon xs"
          aria-label={`复制 ${q}`}
          onClick={() => {
            void navigator.clipboard?.writeText(q).then(
              () => message.success("已复制"),
              () => message.error("复制失败"),
            );
          }}
        >
          <Icon name="copy" size={14} />
        </button>
      </Tip>
      {projectId && (
        <Tip title="在检索页打开">
          <button type="button" className="btn ghost icon xs" aria-label={`检索 ${q}`} onClick={() => navigate(searchHref(projectId, q))}>
            <Icon name="search" size={14} />
          </button>
        </Tip>
      )}
    </span>
  );
}

function QuerySection({ projectId }: { projectId?: string }) {
  return (
    <>
      <table className="tbl help-tbl">
        <thead>
          <tr>
            <th>写法</th>
            <th>含义</th>
          </tr>
        </thead>
        <tbody>
          {QUERY_ROWS.map((r) => (
            <tr key={r.examples[0]}>
              <td className="help-exs">
                {r.examples.map((q) => (
                  <Example key={q} q={q} projectId={projectId} />
                ))}
              </td>
              <td>
                {r.meaning}
                {r.needs && <div className="help-needs">{r.needs}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="help-notes">
        {QUERY_NOTES.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </>
  );
}

function ImportSection() {
  return (
    <>
      <table className="tbl help-tbl">
        <thead>
          <tr>
            <th>格式</th>
            <th>一个文件产生</th>
            <th>规则</th>
          </tr>
        </thead>
        <tbody>
          {FORMAT_ROWS.map((r) => (
            <tr key={r.format}>
              <th scope="row">{r.format}</th>
              <td className="nowrap">{r.unit}</td>
              <td>{r.rule}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>CSV / TSV / XLSX / JSONL 列映射</h3>
      <KvTable rows={MAPPING_ROWS} />
      <h3>语言、去重与上限</h3>
      <KvTable rows={IMPORT_LIMITS} />
    </>
  );
}

function MetricsSection() {
  const [style, setStyle] = useState<Style>("gbt7714");
  const metrics = useHelpMetrics(style);
  const byKey = new Map((metrics.data?.items ?? []).map((m) => [m.key, m]));
  const refs = new Map<string, string>();
  for (const g of METRIC_GROUPS) for (const k of g.keys) for (const r of byKey.get(k)?.references ?? []) refs.set(r.key, r.text);
  return (
    <>
      <div className="row help-style">
        <span className="small muted">文献格式</span>
        <Segmented<Style>
          size="small"
          value={style}
          onChange={setStyle}
          options={[
            { value: "gbt7714", label: "GB/T 7714" },
            { value: "apa", label: "APA" },
          ]}
        />
      </div>
      <ErrorAlert error={metrics.error} />
      {metrics.isPending ? (
        <Skeleton rows={6} />
      ) : (
        metrics.data && (
          <>
            {METRIC_GROUPS.map((g) => (
              <Fragment key={g.title}>
                <h3>{g.title}</h3>
                <table className="tbl help-tbl">
                  <thead>
                    <tr>
                      <th>指标</th>
                      <th>公式</th>
                      <th>文献</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.keys.map((k) => {
                      const m = byKey.get(k);
                      if (!m) return null;
                      return (
                        <tr key={k}>
                          <th scope="row" className="nowrap">
                            {m.name}
                          </th>
                          <td>{m.formula}</td>
                          <td className="nowrap">{m.references.map((r) => r.label).join("；")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Fragment>
            ))}
            <ul className="help-notes">
              {METRIC_NOTES.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <h3>参考文献</h3>
            <ol className="help-refs">
              {[...refs.entries()].map(([k, text]) => (
                <li key={k}>{text}</li>
              ))}
            </ol>
          </>
        )
      )}
    </>
  );
}

function ErrorsSection() {
  return (
    <table className="tbl help-tbl">
      <thead>
        <tr>
          <th>错误码</th>
          <th>含义</th>
          <th>处理</th>
        </tr>
      </thead>
      <tbody>
        {ERROR_ROWS.map((r) => (
          <tr key={r.code}>
            <td>
              <code>{r.code}</code>
            </td>
            <td>{r.meaning}</td>
            <td>{r.fix}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HelpBody({ projectId }: { projectId?: string }) {
  const body: Record<string, React.ReactNode> = {
    query: <QuerySection projectId={projectId} />,
    import: <ImportSection />,
    metrics: <MetricsSection />,
    roles: <KvTable rows={ROLE_ROWS} head={["角色", "权限"]} />,
    privacy: (
      <>
        <KvTable rows={PRIVACY_ROWS} />
        {projectId && (
          <Link className="btn s" to={`/p/${projectId}/settings?tab=privacy`}>
            <Icon name="shield" size={14} />
            设置 · 数据与隐私
          </Link>
        )}
      </>
    ),
    errors: <ErrorsSection />,
  };
  return (
    <div className="help">
      <nav className="help-toc" aria-label="帮助目录">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#help-${s.id}`}>
            {s.title}
          </a>
        ))}
      </nav>
      <div className="help-main">
        {SECTIONS.map((s) => (
          <section key={s.id} id={`help-${s.id}`} className="card" aria-labelledby={`help-${s.id}-h`}>
            <div className="card-head">
              <h2 id={`help-${s.id}-h`}>{s.title}</h2>
            </div>
            <div className="help-sec">{body[s.id]}</div>
          </section>
        ))}
      </div>
    </div>
  );
}

/** /p/:projectId/help inside the shell. */
export default function Help() {
  const { projectId } = useParams();
  return (
    <>
      <PageHeader title="帮助" crumbs={0} />
      <div className="content">
        <HelpBody projectId={projectId} />
      </div>
    </>
  );
}

function lastProject(): string | null {
  try {
    return localStorage.getItem("last-project");
  } catch {
    return null;
  }
}

/** /help: the help of the last opened project; without one, the page alone (no search links). */
export function HelpStandalone() {
  const last = lastProject();
  if (last) return <Navigate to={`/p/${last}/help`} replace />;
  return (
    <div className="help-alone">
      <header className="row">
        <h1 className="grow">帮助</h1>
        <Link className="btn s" to="/">
          项目列表
        </Link>
      </header>
      <HelpBody />
    </div>
  );
}
