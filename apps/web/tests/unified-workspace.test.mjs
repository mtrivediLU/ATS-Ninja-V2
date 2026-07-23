import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { formatAnswersText, recommendedOutreachDraft } from "../lib/artifact-content.ts";

test("formats all returned application answers without inventing content", () => {
  assert.equal(formatAnswersText({ items: [{ question: "Why this role?", answer: "Grounded answer." }], text: "fallback" }), "Why this role?\nGrounded answer.");
  assert.equal(formatAnswersText({ items: [], text: "Returned fallback" }), "Returned fallback");
});

test("uses only the engine-returned first outreach draft as the recommendation", () => {
  const first = { id: "first" };
  assert.equal(recommendedOutreachDraft([first]), first);
  assert.equal(recommendedOutreachDraft([]), null);
});

test("unified workspace composes the one provider result without a card fetch or second poller", async () => {
  const source = await readFile(new URL("../components/product/unified-kit-workspace.tsx", import.meta.url), "utf8");
  assert.match(source, /useKit\(\)/);
  assert.doesNotMatch(source, /getKit\(|setInterval\(/);
  assert.match(source, /PrimaryDocumentCard/);
  assert.match(source, /ArtifactSummarySection/);
});

test("quick PDF control uses the established export client and has an in-flight guard", async () => {
  const source = await readFile(new URL("../components/product/quick-pdf-download.tsx", import.meta.url), "utf8");
  assert.match(source, /exportDocumentPdf/);
  assert.match(source, /if \(exporting \|\| !text\.trim\(\)\) return/);
  assert.match(source, /content_source: edited \? "local_edit" : "generated"/);
});
