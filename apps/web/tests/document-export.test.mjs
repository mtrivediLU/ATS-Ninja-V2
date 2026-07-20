import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, exportDocumentPdf } from "../lib/api-client.ts";

function fakeResponse({ ok, status, headers = {}, jsonBody, blobBody }) {
  return {
    ok,
    status,
    headers: { get: (name) => headers[name.toLowerCase()] ?? null },
    json: async () => jsonBody,
    blob: async () => blobBody,
  };
}

test("exportDocumentPdf returns the blob and the server-computed filename", async () => {
  const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "application/pdf" });
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    fakeResponse({
      ok: true,
      status: 200,
      headers: { "content-disposition": 'attachment; filename="Jane_Doe_Resume_Classic.pdf"' },
      blobBody: blob,
    });
  try {
    const result = await exportDocumentPdf({
      kit_id: "kit-1",
      artifact_type: "resume",
      template_id: "classic",
      content_source: "generated",
    });
    assert.equal(result.filename, "Jane_Doe_Resume_Classic.pdf");
    assert.equal(result.blob, blob);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("exportDocumentPdf falls back to a safe default filename when no header is present", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => fakeResponse({ ok: true, status: 200, blobBody: new Blob(["x"]) });
  try {
    const result = await exportDocumentPdf({
      kit_id: "kit-1",
      artifact_type: "cover_letter",
      template_id: "modern",
      content_source: "generated",
    });
    assert.equal(result.filename, "document.pdf");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("exportDocumentPdf surfaces a safe server-provided detail message on failure", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    fakeResponse({ ok: false, status: 422, jsonBody: { detail: "This kit has no generated Cover Letter to export." } });
  try {
    await assert.rejects(
      () =>
        exportDocumentPdf({
          kit_id: "kit-1",
          artifact_type: "cover_letter",
          template_id: "classic",
          content_source: "generated",
        }),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.message, "This kit has no generated Cover Letter to export.");
        assert.equal(error.kind, "invalid");
        assert.equal(error.status, 422);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("exportDocumentPdf maps an unknown kit to a not-found error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => fakeResponse({ ok: false, status: 404, jsonBody: { detail: "Kit not found" } });
  try {
    await assert.rejects(
      () =>
        exportDocumentPdf({ kit_id: "missing", artifact_type: "resume", template_id: "classic", content_source: "generated" }),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.kind, "not-found");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("exportDocumentPdf reports an unreachable API without leaking the raw fetch error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new TypeError("network down");
  };
  try {
    await assert.rejects(
      () =>
        exportDocumentPdf({ kit_id: "kit-1", artifact_type: "resume", template_id: "classic", content_source: "generated" }),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.kind, "unavailable");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
