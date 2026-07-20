import type { KitCreateInput, KitList, KitRead, ResumeExtraction } from "@/lib/api-types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number | null;
  readonly kind: "unavailable" | "invalid" | "not-found" | "server";

  constructor(message: string, status: number | null, kind: "unavailable" | "invalid" | "not-found" | "server") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("The local API could not be reached. Check that the Docker stack is running.", null, "unavailable");
  }

  if (!response.ok) {
    let detail = "The request could not be completed.";
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string" &&
        body.detail.length <= 300
      ) {
        detail = body.detail;
      }
    } catch {
      // A proxy or unavailable service may return HTML/plain text. Never render it.
    }
    const kind = response.status === 404 ? "not-found" : response.status < 500 ? "invalid" : "server";
    throw new ApiError(detail, response.status, kind);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The API returned a malformed response.", response.status, "server");
  }
}

export function createKit(payload: KitCreateInput, signal?: AbortSignal): Promise<KitRead> {
  return request<KitRead>("/api/v1/kits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

export function extractResume(file: File, signal?: AbortSignal): Promise<ResumeExtraction> {
  const form = new FormData();
  form.append("file", file, file.name);
  return request<ResumeExtraction>("/api/v1/resume-extractions", {
    method: "POST",
    body: form,
    signal,
  });
}

export function getKit(kitId: string, signal?: AbortSignal): Promise<KitRead> {
  return request<KitRead>(`/api/v1/kits/${encodeURIComponent(kitId)}`, { signal });
}

export function listKits(limit = 20, offset = 0, signal?: AbortSignal): Promise<KitList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<KitList>(`/api/v1/kits?${params}`, { signal });
}

export type DocumentExportPayload = {
  kit_id: string;
  artifact_type: "resume" | "cover_letter";
  template_id: "classic" | "modern";
  content_source: "generated" | "local_edit";
  local_edit_text?: string;
};

const FILENAME_FROM_DISPOSITION = /filename="([^"]+)"/;

/**
 * Direct local PDF export: a real binary download, not a print dialog.
 * Bypasses `request<T>` (JSON-only) since the success body is a PDF blob; the
 * error path still parses the same safe `{ detail }` shape as every other
 * endpoint, and the standardized filename comes from the server's
 * Content-Disposition header — this stays the single source of truth for the
 * naming convention rather than duplicating it in TypeScript.
 */
export async function exportDocumentPdf(
  payload: DocumentExportPayload,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/document-exports/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/pdf" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError("The local API could not be reached. Check that the Docker stack is running.", null, "unavailable");
  }

  if (!response.ok) {
    let detail = "The PDF could not be generated.";
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string" &&
        body.detail.length <= 300
      ) {
        detail = body.detail;
      }
    } catch {
      // A proxy or unavailable service may return HTML/plain text. Never render it.
    }
    const kind = response.status === 404 ? "not-found" : response.status < 500 ? "invalid" : "server";
    throw new ApiError(detail, response.status, kind);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = FILENAME_FROM_DISPOSITION.exec(disposition)?.[1] || "document.pdf";
  return { blob, filename };
}
