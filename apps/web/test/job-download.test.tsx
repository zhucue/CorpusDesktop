import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import { JobDownloadLink, downloadJob, filenameFrom } from "../src/lib/download";

vi.setConfig({ testTimeout: 20000 });

function stubClick() {
  const clicked: { href: string; download: string }[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.getAttribute("href") ?? "", download: this.download });
  });
  return clicked;
}

describe("job download", () => {
  it("reads the file name from Content-Disposition", () => {
    expect(filenameFrom(`attachment; filename="hits.xlsx"; filename*=UTF-8''%E6%A3%80%E7%B4%A2.xlsx`)).toBe("检索.xlsx");
    expect(filenameFrom(`attachment; filename="hits.csv"`)).toBe("hits.csv");
    expect(filenameFrom(null)).toBeNull();
  });

  it("checks with the session cookie, aborts the probe and lets the browser download the URL", async () => {
    const clicked = stubClick();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("a,b\n", { status: 200, headers: { "Content-Disposition": `attachment; filename="hits.csv"` } }),
    );
    await downloadJob("j1", "fallback.csv");
    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/j1/download", expect.objectContaining({ method: "GET", credentials: "include" }));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal?.aborted).toBe(true);
    expect(clicked).toEqual([{ href: "/api/jobs/j1/download", download: "hits.csv" }]);
  });

  it("shows the API message for an expired export instead of navigating", async () => {
    const clicked = stubClick();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "EXPORT_EXPIRED", message: "导出文件已过期，请重新导出" } }), { status: 410, headers: { "Content-Type": "application/json" } }),
    );
    render(
      <App>
        <JobDownloadLink jobId="j2" filename="old.csv">
          下载 old.csv
        </JobDownloadLink>
      </App>,
    );
    const link = screen.getByText("下载 old.csv");
    expect(link.getAttribute("href")).toBe("/api/jobs/j2/download");
    fireEvent.click(link);
    await screen.findByText("导出文件已过期，请重新导出");
    await waitFor(() => expect(clicked).toEqual([]));
  });
});
