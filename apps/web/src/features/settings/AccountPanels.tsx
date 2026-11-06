import { App, Spin } from "antd";
import { ErrorAlert } from "../../components/common";
import { PasswordForm } from "../auth/ChangePassword";
import { useSystemInfo } from "./system";

export function PasswordCard() {
  const { message } = App.useApp();
  return (
    <section className="card" aria-label="修改密码">
      <div className="card-head">
        <h2>修改密码</h2>
      </div>
      <div className="set-body pw-card">
        <PasswordForm idPrefix="set-pw" onDone={() => message.success("密码已修改，其他设备需重新登录")} />
      </div>
    </section>
  );
}

const MODEL_ACTIONS = ["助手对话", "LLM 片段与关系预标", "对齐候选（选用模型时）", "文献摘要", "术语抽取"];

/** Where data lives and what leaves the server (contracts/p7.md §六). */
export function PrivacyCard() {
  const info = useSystemInfo();
  const d = info.data;
  const modelHost = d ? (d.model.configured ? (d.model.host ?? "已配置") : "未配置，以上操作不可用") : "";
  const embedText = d ? (d.embed.mode === "remote" ? `发送到 ${d.embed.host ?? "远程服务"}` : "本机模型处理，不外发") : "";
  return (
    <section className="card" aria-label="数据与隐私">
      <div className="card-head">
        <h2 className="grow">数据与隐私</h2>
        {d && <span className="small muted num">版本 {d.version}</span>}
      </div>
      <ErrorAlert error={info.error} style={{ margin: 16 }} />
      {info.isPending ? (
        <Spin style={{ display: "block", margin: 24 }} />
      ) : (
        <dl className="privacy">
          <dt>数据存放</dt>
          <dd>本机 PostgreSQL 数据库与 Docker 数据卷：语料、索引、标注、知识库、导出文件、助手会话。</dd>
          <dt>管理员可见</dt>
          <dd>全部账号及各账号的项目数；不通过界面读取他人项目内容。</dd>
          <dt>发送到外部模型</dt>
          <dd>
            <ul>
              {MODEL_ACTIONS.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <div>
              模型主机：<b>{modelHost}</b>
              {d?.model.configured && d.model.model_id && <span className="muted"> · {d.model.model_id}</span>}
            </div>
          </dd>
          <dt>知识库向量化</dt>
          <dd>{embedText}</dd>
          <dt>备份</dt>
          <dd>保留期限与存放位置由部署方决定。</dd>
        </dl>
      )}
    </section>
  );
}
