import { Alert, Card, Spin } from "antd";
import { Navigate } from "react-router";
import { errorText } from "../api";
import CreateProject from "../CreateProject";
import { useProjects } from "../projects";

export default function Projects() {
  const projects = useProjects();
  if (projects.isPending) return <Spin style={{ display: "block", marginTop: 120 }} />;
  if (projects.error) return <Alert type="error" showIcon message={errorText(projects.error)} style={{ margin: 24 }} />;
  const first = projects.data.items[0];
  if (first) return <Navigate to={`/p/${first.id}/corpora`} replace />;
  return (
    <Card title="新建项目" style={{ maxWidth: 420, margin: "120px auto" }}>
      <CreateProject />
    </Card>
  );
}
