import { act, render, screen } from "@testing-library/react";
import { setPlatformAPI } from "echarts/core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { chartSvg } from "../src/components/results/EChart";

// jsdom has no canvas to measure text with.
setPlatformAPI({ measureText: (text: string) => ({ width: text.length * 12 }) as TextMetrics });
import { hbarOption } from "../src/features/stats/StatChart";
import { getProjectScope, resetScopeStore, setProjectScope, useProjectScope } from "../src/lib/scope";

/** The page in dark mode: dark values on the root element, light ones in the plain `:root` rule (tokens.css). */
function darkPage() {
  const style = document.createElement("style");
  style.id = "tokens";
  style.textContent = `:root { --surface: #FFFFFF; --text-2: #475467; --accent: #1570EF; --font: "Inter Variable", Inter, "Microsoft YaHei", sans-serif; --mono: "JetBrains Mono", monospace; }`;
  document.head.appendChild(style);
  const root = document.documentElement;
  root.setAttribute("data-theme", "dark");
  root.style.setProperty("--surface", "#161A22");
  root.style.setProperty("--text-2", "#B4BCC8");
  root.style.setProperty("--font", `"Inter Variable", Inter, sans-serif`);
}

describe("chart export", () => {
  beforeEach(darkPage);
  afterEach(() => {
    document.getElementById("tokens")?.remove();
    document.documentElement.removeAttribute("style");
    document.documentElement.removeAttribute("data-theme");
  });

  it("is well-formed XML in the light theme on white, whatever the page theme", () => {
    const labels = ["语言", '"hi"', "R&<x"];
    const svg = chartSvg((t) => hbarOption(t, labels, [3, 2, 1], (i) => `${3 - i} · 1,000`), 480, 200);
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    expect(doc.getElementsByTagName("parsererror")).toHaveLength(0);
    expect(doc.documentElement.nodeName).toBe("svg");
    expect(doc.documentElement.getAttribute("xmlns")).toBe("http://www.w3.org/2000/svg");
    // font lists keep their quotes valid inside style="…"
    expect(svg).not.toMatch(/font-family:"/);
    expect(svg).toContain("'Inter Variable'");
    // light text colour and a white background, not the dark page values
    expect(svg).toContain("#475467");
    expect(svg).not.toContain("#B4BCC8");
    expect(svg.toUpperCase()).toContain("#FFFFFF");
    expect(svg).not.toContain("#161A22");
    expect(doc.documentElement.textContent).toContain("R&<x");
  });
});

function Probe({ id }: { id: string }) {
  const [scope] = useProjectScope("p1");
  return <span data-testid={id}>{scope ? JSON.stringify(scope) : "none"}</span>;
}

describe("project scope store", () => {
  beforeEach(() => {
    localStorage.clear();
    resetScopeStore();
  });

  it("is one scope for every reader and persists per project", () => {
    render(
      <>
        <Probe id="stats" />
        <Probe id="crumbs" />
      </>,
    );
    expect(screen.getByTestId("stats").textContent).toBe("none");
    act(() => setProjectScope("p1", { corpus_id: "wiki" }));
    expect(screen.getByTestId("stats").textContent).toBe('{"corpus_id":"wiki"}');
    expect(screen.getByTestId("crumbs").textContent).toBe('{"corpus_id":"wiki"}');
    expect(JSON.parse(localStorage.getItem("scope:p1")!)).toEqual({ corpus_id: "wiki" });
    expect(getProjectScope("p2")).toBeNull();
    resetScopeStore();
    expect(getProjectScope("p1")).toEqual({ corpus_id: "wiki" });
  });

  it("stores only the corpus or subcorpus, never a temporary filter", () => {
    setProjectScope("p1", { corpus_id: "wiki", filter: { year: [2020] } } as never);
    expect(getProjectScope("p1")).toEqual({ corpus_id: "wiki" });
    setProjectScope("p1", { subcorpus_id: "s1" });
    expect(getProjectScope("p1")).toEqual({ subcorpus_id: "s1" });
  });
});
