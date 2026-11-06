import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { api, type User } from "../../api";
import { ErrorAlert } from "../../components/common";
import { Icon } from "../../components/Icon";
import { useMe } from "../../lib/data";
import { safeNext } from "./next";
import "./login.css";

const MIN = 12;
const MAX = 1024;

function problem(oldPw: string, next: string, again: string): string | null {
  if (!oldPw || !next) return "请填写原密码和新密码";
  if (next.length < MIN || next.length > MAX) return `新密码长度须为 ${MIN} 到 ${MAX} 位`;
  if (next === oldPw) return "新密码不能与原密码相同";
  if (next !== again) return "两次输入的新密码不一致";
  return null;
}

/** POST /auth/password. Other sessions and agent tokens are revoked; this one stays. */
export function PasswordForm({ temporary, onDone, idPrefix = "pw" }: { temporary?: boolean; onDone: (u: User) => void; idPrefix?: string }) {
  const qc = useQueryClient();
  const [oldPw, setOldPw] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.post<User>("/auth/password", { old_password: oldPw, new_password: next }),
    onSuccess: (u) => {
      qc.setQueryData(["me"], u);
      setOldPw("");
      setNext("");
      setAgain("");
      onDone(u);
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const p = problem(oldPw, next, again);
    setShown(p);
    if (!p) change.mutate();
  }

  const field = (id: string, label: string, value: string, set: (v: string) => void, auto: string) => (
    <div className="field">
      <label htmlFor={`${idPrefix}-${id}`}>{label}</label>
      <input
        className="input"
        id={`${idPrefix}-${id}`}
        type="password"
        autoComplete={auto}
        maxLength={MAX}
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </div>
  );

  return (
    <form className="col gap-16" onSubmit={submit} noValidate>
      {field("old", temporary ? "临时密码" : "原密码", oldPw, setOldPw, "current-password")}
      {field("new", `新密码（至少 ${MIN} 位）`, next, setNext, "new-password")}
      {field("again", "再次输入新密码", again, setAgain, "new-password")}
      {shown && (
        <div className="alert err" role="alert">
          <Icon name="alert" size={14} />
          <span>{shown}</span>
        </div>
      )}
      {!shown && <ErrorAlert error={change.error} />}
      <button className="btn p" type="submit" disabled={change.isPending}>
        {change.isPending ? (
          <>
            <span className="spin" />
            保存中
          </>
        ) : (
          "修改密码"
        )}
      </button>
    </form>
  );
}

/** Route /password: forced after logging in with a temporary password (must_change_password). */
export default function ChangePassword() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const me = useMe();
  const temporary = !!me.data?.must_change_password;

  function done() {
    navigate(safeNext(params.get("next")), { replace: true });
  }

  async function logout() {
    try {
      await api.post("/auth/logout");
    } finally {
      qc.clear();
      navigate("/login", { replace: true });
    }
  }

  return (
    <div className="login-page dotgrid">
      <span className="glow a" aria-hidden />
      <span className="glow b" aria-hidden />
      <main className="card login">
        <span className="brand-mark" style={{ ["--i" as string]: 0 }}>
          <Icon name="lock" size={20} />
        </span>
        <h1 style={{ ["--i" as string]: 1 }}>{temporary ? "设置新密码" : "修改密码"}</h1>
        <div style={{ ["--i" as string]: 2, marginTop: 8 }} className="sm muted">
          {me.data?.email}
        </div>
        <div style={{ ["--i" as string]: 3, marginTop: 20 }}>
          <PasswordForm temporary={temporary} onDone={done} />
        </div>
        <button className="btn ghost s login-alt" type="button" style={{ ["--i" as string]: 4 }} onClick={logout}>
          <Icon name="logout" size={14} />
          退出登录
        </button>
      </main>
    </div>
  );
}
