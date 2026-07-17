import type { KitCreateInput, KitList, KitRead } from "@/lib/api-types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly kind: "unavailable" | "invalid" | "not-found" | "server",
  ) {
    super(message);
    this.name = "ApiError";
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

export function getKit(kitId: string, signal?: AbortSignal): Promise<KitRead> {
  return request<KitRead>(`/api/v1/kits/${encodeURIComponent(kitId)}`, { signal });
}

export function listKits(limit = 20, offset = 0, signal?: AbortSignal): Promise<KitList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<KitList>(`/api/v1/kits?${params}`, { signal });
}
