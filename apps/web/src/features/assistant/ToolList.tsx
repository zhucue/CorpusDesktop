import { useState } from "react";
import { AGENT_TOOLS, CONFIRM_TOOLS, TOOL_VIEW } from "../../components/global/tools";
import { Icon } from "../../components/Icon";

/** The assistant's tools by capability, Chinese names; groups fold open on click. `used` highlights tools called in this conversation. */
export function ToolList({ used }: { used?: Set<string> }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="tool-list">
      {AGENT_TOOLS.map((g) => {
        const on = open === g.group;
        const usedHere = g.tools.filter((t) => used?.has(t)).length;
        return (
          <div key={g.group} className="tool-grp" data-open={on}>
            <button className="tool-grp-head" type="button" aria-expanded={on} onClick={() => setOpen(on ? null : g.group)}>
              <Icon name="down" size={14} className="chev" />
              <span className="grow">{g.group}</span>
              {usedHere > 0 && <span className="tool-used">已用 {usedHere}</span>}
              <span className="num muted">{g.tools.length}</span>
            </button>
            {on && (
              <ul className="tool-items">
                {g.tools.map((t) => (
                  <li key={t} className={used?.has(t) ? "used" : undefined}>
                    <Icon name={TOOL_VIEW[t]?.icon ?? "tool"} size={14} />
                    <span className="grow">{TOOL_VIEW[t]?.title ?? t}</span>
                    {CONFIRM_TOOLS.has(t) && <span className="tool-confirm">需确认</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
