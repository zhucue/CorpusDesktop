import { useQueryClient } from "@tanstack/react-query";
import { Spin } from "antd";
import { useEffect } from "react";
import { Link } from "react-router";
import { ApiError } from "../../api";
import { Monogram } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useProject, useProjectId, useProjects } from "../../lib/data";
import "./settings.css";

/** 404 on the project: deleted, or the user was removed from it (non-members get 404). */
export const isGone = (e: unknown) => e instanceof ApiError && e.status === 404;

/**
 * Wraps the project shell (route /p/:projectId). When the project answers 404 the whole shell gives way to
 * "你已不是该项目成员" with the user's other projects and 新建项目, instead of every page showing NOT_FOUND.
 */
export default function ProjectGate({ children }: { children: React.ReactNode }) {
  const project = useProject();
  if (isGone(project.error)) return <NoLongerMember />;
  return <>{children}</>;
}

function NoLongerMember() {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const projects = useProjects();
  const others = (projects.data?.items ?? []).filter((p) => p.id !== projectId);

  useEffect(() => {
    // stale caches of the lost project would show its old role and data again
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "project" && q.queryKey.includes(projectId) });
    try {
      if (localStorage.getItem("last-project") === projectId) localStorage.removeItem("last-project");
    } catch {
      /* storage unavailable */
    }
    void qc.invalidateQueries({ queryKey: ["projects"] });
  }, [projectId, qc]);

  return (
    <div className="gone-page dotgrid">
      <main className="card gone" role="alert">
        <span className="gone-ic" aria-hidden>
          <Icon name="lock" size={20} />
        </span>
        <h1>你已不是该项目成员</h1>
        <p className="muted sm">项目已删除，或负责人已将你移出。</p>
        {projects.isPending ? (
          <Spin />
        ) : others.length > 0 ? (
          <nav className="col" style={{ gap: 6 }} aria-label="我的项目">
            {others.map((p) => (
              <Link key={p.id} className="gone-proj" to={`/p/${p.id}/corpora`}>
                <Monogram name={p.name} />
                <span className="grow ellipsis">{p.name}</span>
                <Icon name="right" size={14} className="muted" />
              </Link>
            ))}
          </nav>
        ) : null}
        <Link className="btn p" to="/onboarding">
          <Icon name="plus" size={14} />
          新建项目
        </Link>
      </main>
    </div>
  );
}
