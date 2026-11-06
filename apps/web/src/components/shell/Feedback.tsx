import { useMutation } from "@tanstack/react-query";
import { App, Input, Modal } from "antd";
import { useState } from "react";
import { useLocation, useParams } from "react-router";
import { api } from "../../api";
import { ErrorAlert, Tip } from "../common";
import { Icon } from "../Icon";

export const MAX_FEEDBACK = 2000;

/** POST /feedback: text with the current route; the API adds APP_VERSION. No project content (contracts/p9.md §六). */
export function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const loc = useLocation();
  const { projectId } = useParams();
  const [text, setText] = useState("");
  const send = useMutation({
    mutationFn: () =>
      api.post("/feedback", {
        text: text.trim(),
        page: (loc.pathname + loc.search).slice(0, 500),
        ...(projectId ? { project_id: projectId } : {}),
      }),
    onSuccess: () => {
      setText("");
      message.success("已收到");
      onClose();
    },
  });
  const len = Array.from(text.trim()).length;
  return (
    <Modal
      title="反馈问题"
      open={open}
      onCancel={() => {
        send.reset();
        onClose();
      }}
      okText="提交"
      cancelText="取消"
      okButtonProps={{ disabled: len === 0 || len > MAX_FEEDBACK, loading: send.isPending }}
      onOk={() => send.mutate()}
      destroyOnHidden
      width={480}
    >
      <div className="col" style={{ gap: 10 }}>
        <Input.TextArea
          aria-label="反馈内容"
          value={text}
          rows={6}
          maxLength={MAX_FEEDBACK}
          showCount
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        <ErrorAlert error={send.error} />
      </div>
    </Modal>
  );
}

export function FeedbackButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tip title="反馈问题">
        <button className="btn ghost icon" type="button" aria-label="反馈问题" onClick={() => setOpen(true)}>
          <Icon name="feedback" />
        </button>
      </Tip>
      <FeedbackDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
