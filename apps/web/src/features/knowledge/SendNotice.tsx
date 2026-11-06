import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

/** The part of GET /system/info (contracts/p7.md §六) these notices need; the shared type lives in api/types.ts. */
interface SystemInfo {
  model: { configured: boolean; host: string | null; model_id: string | null };
}

/** Host of the chat model the platform sends text to; null when no model is configured (or the info failed). */
export function useModelHost(enabled = true): string | null {
  const info = useQuery({
    queryKey: ["system-info"],
    queryFn: () => api.get<SystemInfo>("/system/info"),
    staleTime: 5 * 60_000,
    retry: false,
    enabled,
    meta: { background: true },
  });
  const m = info.data?.model;
  return m?.configured && m.host ? m.host : null;
}

/** One line before an action that sends text to the external model, e.g. 将把所选句子发送到 api.example.com. */
export function SendNotice({ what, host, style }: { what: string; host: string | null; style?: React.CSSProperties }) {
  if (!host) return null;
  return (
    <div className="sm" style={style}>
      将把{what}发送到 <span className="mono">{host}</span>
    </div>
  );
}
