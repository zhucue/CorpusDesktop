import { Renderer } from "@openuidev/react-lang";
import { ErrorBoundary } from "../components/common/ErrorBoundary";
import { library, RENDERERS } from "./library";

/** JSON fallback: `{component, props}` (or an array of them). Returns null when the text is not that shape. */
export function parseJsonBlock(text: string): { component: string; props: Record<string, unknown> }[] | null {
  const t = text.trim();
  if (!t.startsWith("{") && !t.startsWith("[")) return null;
  try {
    const v: unknown = JSON.parse(t);
    const list = Array.isArray(v) ? v : [v];
    if (list.every((x) => x && typeof x === "object" && typeof (x as { component?: unknown }).component === "string")) {
      return list.map((x) => ({ component: (x as { component: string }).component, props: ((x as { props?: object }).props ?? {}) as Record<string, unknown> }));
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * One `ui` message part. OpenUI Lang (the agent's format) renders through the official renderer;
 * a JSON `{component, props}` block renders the same registered components directly.
 */
export default function UiBlock({ lang, streaming, index = 0 }: { lang: string; streaming?: boolean; index?: number }) {
  const json = parseJsonBlock(lang);
  if (json) {
    return (
      <ErrorBoundary retry style={{ margin: 0 }}>
        {json.map((b, i) => {
          const C = RENDERERS[b.component] as React.FC<Record<string, unknown>> | undefined;
          return (
            <div key={i} style={{ ["--i" as string]: index + i }} className="ui-block">
              {C ? <C {...b.props} /> : <div className="callout warning">未注册的组件：{b.component}</div>}
            </div>
          );
        })}
      </ErrorBoundary>
    );
  }
  const trimmed = lang.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    // Incomplete JSON while streaming.
    return streaming ? <span className="skel h28" /> : <div className="callout warning">无法解析的组件数据</div>;
  }
  return (
    <div className="ui-block" style={{ ["--i" as string]: index }}>
      <ErrorBoundary retry style={{ margin: 0 }}>
        <Renderer response={lang} library={library} isStreaming={!!streaming} />
      </ErrorBoundary>
    </div>
  );
}
