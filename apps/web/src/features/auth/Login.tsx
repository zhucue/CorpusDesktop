import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ApiError, api, errorCode, errorText, type User } from "../../api";
import { Icon } from "../../components/Icon";
import "./login.css";

export default function Login() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [shake, setShake] = useState(0);
  const pwRef = useRef<HTMLInputElement>(null);
  const login = useMutation({
    mutationFn: () => api.post<User>("/auth/login", { email: email.trim(), password }),
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(["me"], user);
      const next = params.get("next");
      navigate(next && next.startsWith("/") && !next.startsWith("/login") ? next : "/", { replace: true });
    },
    onError: () => setShake((n) => n + 1),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setShake((n) => n + 1);
      pwRef.current?.focus();
      return;
    }
    login.mutate();
  }

  const err = login.error;
  const badCredentials = err instanceof ApiError && err.status === 401;
  return (
    <div className="login-page dotgrid">
      <span className="glow a" aria-hidden />
      <span className="glow b" aria-hidden />
      <main className={`card login ${shake ? "shake" : ""}`} onAnimationEnd={(e) => e.animationName === "shake" && setShake(0)}>
        <span className="brand-mark" style={{ ["--i" as string]: 0 }}>
          <Icon name="hash" size={20} />
        </span>
        <h1 style={{ ["--i" as string]: 1 }}>登录语料研究平台</h1>
        <form className="col gap-16" style={{ ["--i" as string]: 2, marginTop: 24 }} onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="email">邮箱</label>
            <input className="input" id="email" type="email" autoComplete="username" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pw">密码</label>
            <div className="pw-wrap">
              <input
                ref={pwRef}
                className="input"
                id="pw"
                type={show ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button className="btn ghost icon" type="button" aria-label={show ? "隐藏密码" : "显示密码"} onClick={() => setShow((s) => !s)}>
                <Icon name="eye" size={14} />
              </button>
            </div>
          </div>
          {err && (
            <div className="alert err" role="alert">
              <Icon name="alert" size={14} />
              <span>
                {badCredentials ? "邮箱或密码错误" : errorText(err)}
                {!badCredentials && errorCode(err) && <span className="err-code">{errorCode(err)}</span>}
              </span>
            </div>
          )}
          <button className="btn p" type="submit" disabled={login.isPending}>
            {login.isPending ? (
              <>
                <span className="spin" />
                登录中
              </>
            ) : (
              "登录"
            )}
          </button>
        </form>
      </main>
    </div>
  );
}
