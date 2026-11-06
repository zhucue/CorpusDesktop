import { App } from "antd";
import { useCallback, type ReactNode } from "react";
import { ApiError, errorFromResponse, errorText, unavailableText } from "../api";

export const jobDownloadUrl = (jobId: string) => `/api/jobs/${jobId}/download`;

/** File name from Content-Disposition: RFC 5987 `filename*=UTF-8''…` first, then `filename="…"`. */
export function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const star = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[2].trim().replace(/^"|"$/g, ""));
    } catch {
      /* malformed: fall back to filename= */
    }
  }
  const plain = /filename\s*=\s*("([^"]*)"|[^;]+)/i.exec(disposition);
  return plain ? (plain[2] ?? plain[1]).trim() : null;
}

/**
 * Check the job's file with a GET (session cookie): on 2xx the request is aborted after the headers and the browser
 * downloads the URL itself (streamed, with its own progress); a non-2xx answer (410 EXPORT_EXPIRED, 404…) throws an
 * ApiError carrying the API's Chinese message instead of navigating to a JSON page.
 */
export async function downloadJob(jobId: string, fallbackName = ""): Promise<void> {
  const url = jobDownloadUrl(jobId);
  const probe = new AbortController();
  let res: Response;
  try {
    res = await fetch(url, { method: "GET", credentials: "include", signal: probe.signal });
  } catch {
    throw new ApiError(0, "UNAVAILABLE", unavailableText("GET"));
  }
  if (!res.ok) throw await errorFromResponse(res, "GET");
  probe.abort();
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameFrom(res.headers.get("Content-Disposition")) || fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** downloadJob with the failure shown as an error message. */
export function useJobDownload() {
  const { message } = App.useApp();
  return useCallback(
    (jobId: string, fallbackName?: string) =>
      downloadJob(jobId, fallbackName).catch((e) => {
        message.error(errorText(e));
      }),
    [message],
  );
}

/** A 下载 link for a finished export job; the href stays for status-bar preview, the click fetches. */
export function JobDownloadLink({ jobId, filename, className, title, children }: { jobId: string; filename?: string; className?: string; title?: string; children: ReactNode }) {
  const download = useJobDownload();
  return (
    <a
      className={className}
      title={title}
      href={jobDownloadUrl(jobId)}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        void download(jobId, filename);
      }}
    >
      {children}
    </a>
  );
}
