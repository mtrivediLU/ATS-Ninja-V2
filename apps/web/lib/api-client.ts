import type {
  ChangeActionRequestInput,
  KitCreateInput,
  KitList,
  KitRead,
  ResumeExtraction,
} from "@/lib/api-types";

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

/**
 * Apply a batch of accept/reject/restore change actions to a completed v5 or v6 kit.
 * Returns the updated kit with an incremented revision. A 409 (revision
 * conflict) or 422 (irreversible change) surfaces as an {@link ApiError}.
 */
export function applyChangeActions(
  kitId: string,
  payload: ChangeActionRequestInput,
  signal?: AbortSignal,
): Promise<KitRead> {
  return request<KitRead>(`/api/v1/kits/${encodeURIComponent(kitId)}/change-actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

/** Hard-delete a local kit. Resolves on 204; a missing kit throws a not-found ApiError. */
export async function deleteKit(kitId: string, signal?: AbortSignal): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/kits/${encodeURIComponent(kitId)}`, {
      method: "DELETE",
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError("The local API could not be reached. Check that the Docker stack is running.", null, "unavailable");
  }
  if (response.status === 204) return;
  const kind = response.status === 404 ? "not-found" : response.status < 500 ? "invalid" : "server";
  throw new ApiError("The kit could not be deleted.", response.status, kind);
}

/** Regenerate a kit from its stored inputs; returns the new linked pending kit. */
export function regenerateKit(kitId: string, signal?: AbortSignal): Promise<KitRead> {
  return request<KitRead>(`/api/v1/kits/${encodeURIComponent(kitId)}/regenerate`, {
    method: "POST",
    signal,
  });
}

export type DocumentExportPayload = {
  kit_id: string;
  artifact_type: "resume" | "cover_letter";
  template_id: "classic" | "modern";
  content_source: "generated" | "local_edit";
  local_edit_text?: string;
};

const FILENAME_FROM_DISPOSITION = /filename="([^"]+)"/;

const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/**
 * The shared binary-export request both `exportDocumentPdf` and
 * `exportDocumentDocx` use. Bypasses `request<T>` (JSON-only) since the
 * success body is a document blob; the error path still parses the same safe
 * `{ detail }` shape as every other endpoint, and the standardized filename
 * comes from the server's Content-Disposition header — this stays the single
 * source of truth for the naming convention rather than duplicating it in
 * TypeScript.
 */
async function exportDocument(
  endpoint: "pdf" | "docx",
  acceptMimeType: string,
  fallbackFilename: string,
  payload: DocumentExportPayload,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/document-exports/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: acceptMimeType },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiError("The local API could not be reached. Check that the Docker stack is running.", null, "unavailable");
  }

  if (!response.ok) {
    let detail = `The ${endpoint.toUpperCase()} could not be generated.`;
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
  const filename = FILENAME_FROM_DISPOSITION.exec(disposition)?.[1] || fallbackFilename;
  return { blob, filename };
}

/** Direct local PDF export: a real binary download, not a print dialog. */
export function exportDocumentPdf(
  payload: DocumentExportPayload,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  return exportDocument("pdf", "application/pdf", "document.pdf", payload, signal);
}

/** Direct local Word (.docx) export, parallel to the PDF export above. */
export function exportDocumentDocx(
  payload: DocumentExportPayload,
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  return exportDocument("docx", DOCX_MEDIA_TYPE, "document.docx", payload, signal);
}
