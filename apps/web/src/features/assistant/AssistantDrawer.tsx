import { useState } from "react";
import { useNavigate } from "react-router";
import { Icon } from "../../components/Icon";
import { Tip } from "../../components/common";
import { useShell } from "../../components/shell/shell";
import { readJson, writeJson } from "../../lib/storage";
import "./assistant.css";
import AssistantPanel from "./AssistantPanel";

/** 420 px side panel without mask; scope defaults to the current page (search: search scope + hit count). */
export default function AssistantDrawer({ onClose }: { onClose: () => void }) {
  const shell = useShell();
  const navigate = useNavigate();
  const key = `drawer-session:${shell.projectId}`;
  const [sessionId, setSessionId] = useState<string | null>(() => readJson<string | null>(key, null));
  const ctx = shell.assistantContext;
  const scope = ctx?.scope ?? shell.scope;
  const label = ctx?.label ?? shell.scopeInfo.name;

  return (
    <aside className="asst-drawer" aria-label="助手">
      <div className="drawer-head">
        <Icon name="spark" />
        <h2 className="grow">助手</h2>
        <Tip title="新对话">
          <button
            className="btn ghost icon"
            type="button"
            aria-label="新对话"
            onClick={() => {
              setSessionId(null);
              writeJson(key, null);
            }}
          >
            <Icon name="plus" />
          </button>
        </Tip>
        <Tip title="在助手页打开">
          <button className="btn ghost icon" type="button" aria-label="在助手页打开" onClick={() => navigate(`/p/${shell.projectId}/assistant${sessionId ? `/${sessionId}` : ""}`)}>
            <Icon name="external" />
          </button>
        </Tip>
        <Tip title="关闭">
          <button className="btn ghost icon" type="button" aria-label="关闭助手" onClick={onClose}>
            <Icon name="x" />
          </button>
        </Tip>
      </div>
      <AssistantPanel
        compact
        projectId={shell.projectId}
        sessionId={sessionId}
        onSessionCreated={(s) => {
          setSessionId(s.id);
          writeJson(key, s.id);
        }}
        scope={scope}
        scopeLabel={label}
      />
    </aside>
  );
}
