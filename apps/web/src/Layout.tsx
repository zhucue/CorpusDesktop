import { DatabaseOutlined, PlusOutlined, ProfileOutlined, SearchOutlined, SettingOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Layout as AntLayout, Button, Menu, Modal, Select, Space, Typography } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { api } from "./api";
import { useMe } from "./App";
import CreateProject from "./CreateProject";
import { useProjectId, useProjects } from "./projects";

const nav = [
  { key: "corpora", icon: <DatabaseOutlined />, label: "语料库" },
  { key: "search", icon: <SearchOutlined />, label: "检索" },
  { key: "jobs", icon: <ProfileOutlined />, label: "任务" },
  { key: "settings", icon: <SettingOutlined />, label: "项目设置" },
];

export default function Layout() {
  const projectId = useProjectId();
  const projects = useProjects();
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [creating, setCreating] = useState(false);
  const section = location.pathname.split("/")[3] ?? "corpora";

  async function logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      navigate("/login", { replace: true });
    }
  }

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <AntLayout.Sider theme="light" width={168} style={{ borderRight: "1px solid #f0f0f0" }}>
        <Typography.Title level={5} style={{ padding: "16px 20px 8px", margin: 0 }}>
          语料研究平台
        </Typography.Title>
        <Menu
          mode="inline"
          selectedKeys={[section]}
          items={nav}
          onClick={(e) => navigate(`/p/${projectId}/${e.key}`)}
          style={{ borderInlineEnd: "none" }}
        />
      </AntLayout.Sider>
      <AntLayout>
        <AntLayout.Header
          style={{
            background: "#fff",
            padding: "0 20px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid #f0f0f0",
          }}
        >
          <Space>
            <Select
              style={{ width: 240 }}
              value={projectId}
              loading={projects.isPending}
              options={projects.data?.items.map((p) => ({ value: p.id, label: p.name }))}
              onChange={(id) => navigate(`/p/${id}/${section}`)}
            />
            <Button icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              新建项目
            </Button>
          </Space>
          <Space>
            <Typography.Text>{me.data?.display_name || me.data?.email}</Typography.Text>
            <Button type="link" onClick={logout}>
              退出
            </Button>
          </Space>
        </AntLayout.Header>
        <AntLayout.Content style={{ padding: 20 }}>
          <Outlet />
        </AntLayout.Content>
      </AntLayout>
      <Modal title="新建项目" open={creating} footer={null} onCancel={() => setCreating(false)} destroyOnClose>
        <CreateProject onDone={() => setCreating(false)} />
      </Modal>
    </AntLayout>
  );
}
