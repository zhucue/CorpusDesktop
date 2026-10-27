import { Alert, Spin } from "antd";
import { Navigate } from "react-router";
import { errorText } from "../../api";
import { useProjects } from "../../lib/data";

/** Entry: users without a project go to onboarding; others to the last project they used. */
export default function Projects() {
  const projects = useProjects();
  if (projects.isPending) return <Spin style={{ display: "block", marginTop: 120 }} />;
  if (projects.error) return <Alert type="error" showIcon message={errorText(projects.error)} style={{ margin: 24 }} />;
  const items = projects.data.items;
  if (items.length === 0) return <Navigate to="/onboarding" replace />;
  let last: string | null = null;
  try {
    last = localStorage.getItem("last-project");
  } catch {
    /* storage unavailable */
  }
  const target = items.find((p) => p.id === last) ?? items[0];
  return <Navigate to={`/p/${target.id}/corpora`} replace />;
}
