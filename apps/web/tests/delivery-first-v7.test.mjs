import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { artifactPresentationState } from "../lib/artifact-presentation.ts";
import { deliveredArtifactCount, effectiveKitStatus, hasDeliveredArtifact, kitTarget } from "../lib/product.ts";
import { buildHeadline, scoreComparisonState } from "../lib/results-presentation.ts";

const read = (rel) => readFile(new URL(rel, import.meta.url), "utf8");

test("fallback score uses the honest delivered-resume label and explanation", () => {
  const state = scoreComparisonState(33, 33, true);
  assert.equal(state.deliveredLabel, "Delivered résumé match");
  assert.equal(state.deltaLabel, "0 · No safe evidence-backed improvement was accepted.");
  assert.match(state.srSummary, /Delivered resume keyword match: 33 out of 100/);
  assert.doesNotMatch(state.srSummary, /Tailored resume keyword match/);
  assert.match(state.noteLabel ?? "", /source-preserving résumé that was delivered/);
});

test("v7 delivery state preserves a fallback document despite legacy fatal metadata", () => {
  const validation = {
    status: "rejected",
    fatal: true,
    errors: ["legacy diagnostic"],
    warnings: [],
    repaired_claims: 0,
    rejected_claims: 0,
  };
  assert.equal(
    artifactPresentationState(validation, "Source-preserving resume", false, "generated_with_fallback"),
    "generated-with-fallback",
  );
  assert.equal(
    artifactPresentationState(validation, "Source-preserving resume", false, "generated"),
    "warning",
  );
  assert.equal(
    artifactPresentationState(validation, "Source-preserving resume", false, "failed"),
    "failed",
  );
});

test("v7 explicit target and confidence take precedence over legacy artifact fields", () => {
  const target = kitTarget({
    result: {
      target_role: "IT Administrator",
      target_company: "ClaimSecure",
      target_confidence: 0.42,
      linkedin_outreach: {
        drafts: [{ target_role: "Legacy Role", target_company: "Legacy Company" }],
        target_context: [],
      },
    },
  });
  assert.deepEqual(target, { role: "IT Administrator", company: "ClaimSecure", confidence: 0.42 });
});

test("v7 API types cover kit, document, finding, delivery, and optimization states", async () => {
  const source = await read("../lib/api-types.ts");
  for (const status of ["partially_completed", "needs_input_review"]) {
    assert.match(source, new RegExp(`"${status}"`));
  }
  for (const state of ["generated", "generated_with_fallback", "needs_input_review", "failed", "not_requested"]) {
    assert.match(source, new RegExp(`"${state}"`));
  }
  assert.match(source, /export interface ValidationFinding/);
  assert.match(source, /severity: ValidationSeverity/);
  assert.match(source, /export interface DeliveryReport/);
  assert.match(source, /delivery_reports\?: Partial<Record<ArtifactKind, DeliveryReport>>/);
  assert.match(source, /state\?: KitState/);
  assert.match(source, /delivery_state\?: DocumentState/);
  assert.match(source, /calibration_suppressed\?: string\[\]/);
  assert.match(source, /target_role\?: string \| null/);
  assert.match(source, /target_company\?: string \| null/);
  assert.match(source, /target_confidence\?: number \| null/);
});

test("v7 and partial kits remain in the results workspace with delivered artifacts", async () => {
  const source = await read("../components/product/unified-kit-workspace.tsx");
  assert.match(source, /application-kit\/v7/);
  assert.match(source, /lifecycle === "partially_completed"/);
  assert.match(source, /Successfully generated documents remain available below/);
  assert.match(source, /deliveryReport=\{result\.delivery_reports\?\.resume\}/);
  assert.match(source, /deliveryReport=\{result\.delivery_reports\?\.cover_letter\}/);
  assert.match(source, /resumeState=\{result\.delivery_reports\?\.resume\?\.state\}/);
});

test("source-preserving resume fallback is delivered with the exact honest banner", async () => {
  const notice = await read("../components/product/delivery-notice.tsx");
  assert.match(
    notice,
    /We delivered your resume preserving your original content; here's why tailoring was limited/,
  );
  assert.match(notice, /No safe evidence-backed improvement was accepted/);

  const card = await read("../components/product/primary-document-card.tsx");
  assert.match(card, /generated-with-fallback/);
  assert.match(card, /Source-preserving delivered version/);
  assert.match(card, /<DeliveryFallbackBanner/);
  assert.match(card, /deliveryReport\?\.state/);
});

test("needs-input-review is an actionable recovery state while partial is not blocked", async () => {
  const boundary = await read("../components/product/kit-state.tsx");
  assert.match(boundary, /effectiveKitStatus\(kit\)/);
  assert.match(boundary, /!hasDeliveredArtifact\(kit\.result\)/);
  assert.match(boundary, /Review inputs in a new Kit/);
  assert.doesNotMatch(boundary, /kit\.status === "partially_completed"[\s\S]*?<RecoveryState/);

  const recovery = await read("../components/product/recovery-state.tsx");
  assert.match(recovery, /Review your input before trying again/);
  assert.match(recovery, /could not be interpreted confidently enough/);

  assert.equal(
    hasDeliveredArtifact({
      delivery_reports: {
        resume: {
          state: "needs_input_review",
          findings: [],
          fallback_reason: "Review the extraction.",
          calibration_suppressed: [],
        },
        cover_letter: {
          state: "generated",
          findings: [],
          fallback_reason: null,
          calibration_suppressed: [],
        },
      },
    }),
    true,
  );
  assert.equal(
    hasDeliveredArtifact({
      delivery_reports: {
        resume: {
          state: "needs_input_review",
          findings: [],
          fallback_reason: "Review the extraction.",
          calibration_suppressed: [],
        },
      },
    }),
    false,
  );

  const workspace = await read("../components/product/unified-kit-workspace.tsx");
  assert.match(workspace, /lifecycle === "needs_input_review"/);
  assert.match(workspace, /Successfully delivered[\s\\n]+artifacts remain available below/);
});

test("delivery state reaches full workspaces and trust presentation", async () => {
  const route = await read("../components/product/artifact-route.tsx");
  assert.match(route, /deliveryState=\{deliveryReport\?\.state\}/);

  const documents = await read("../components/product/document-workspaces.tsx");
  assert.match(documents, /deliveryState=\{deliveryState\}/);
  assert.match(documents, /generated_with_fallback[\s\S]*?"Delivered resume"/);

  const trust = await read("../components/product/trust-summary.tsx");
  assert.match(trust, /artifactPresentationState\(validation, text, manuallyEdited, deliveryState\)/);
  assert.match(trust, /Delivered with fallback/);
});

test("low-confidence explicit targets are editable locally without claiming persistence", async () => {
  const source = await read("../components/product/results-header.tsx");
  assert.match(source, /target\.confidence !== null && target\.confidence < 0\.7/);
  assert.match(source, /Is this right\?/);
  assert.match(source, /Target role/);
  assert.match(source, /Target company/);
  assert.match(source, /These local edits do not change generated documents/);

  const product = await read("../lib/product.ts");
  assert.match(product, /target_company\?\.trim/);
  assert.match(product, /target_role\?\.trim/);
  assert.match(product, /target_confidence/);
});

test("history recognizes v7 and exposes both new lifecycle filters", async () => {
  const source = await read("../components/product/history-workspace.tsx");
  assert.match(source, /"partially_completed"/);
  assert.match(source, /"needs_input_review"/);
  assert.match(source, /schemaVersion !== "application-kit\/v7"/);
});

test("result lifecycle and reports override stale transport labels", () => {
  assert.equal(effectiveKitStatus({ status: "completed", result: { state: "failed" } }), "failed");
  assert.equal(effectiveKitStatus({ status: "processing", result: null }), "processing");
  assert.equal(
    deliveredArtifactCount({ delivery_reports: { resume: { state: "generated", findings: [], fallback_reason: null, calibration_suppressed: [] }, cover_letter: { state: "failed", findings: [], fallback_reason: null, calibration_suppressed: [] } } }),
    1,
  );
});

test("non-completed and unconfirmed low-confidence headlines never claim ready", () => {
  assert.doesNotMatch(buildHeadline({ name: "A", role: "R", company: "C", hasRole: true, hasCompany: true, lifecycle: "partially_completed" }), /ready/i);
  assert.doesNotMatch(buildHeadline({ name: "A", role: "R", company: "C", hasRole: true, hasCompany: true, lifecycle: "needs_input_review" }), /ready/i);
  assert.match(buildHeadline({ name: "", role: "R", company: "C", hasRole: true, hasCompany: true, targetConfirmed: false }), /Review the detected role/i);
});
