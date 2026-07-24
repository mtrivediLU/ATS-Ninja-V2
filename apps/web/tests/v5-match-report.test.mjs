import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (rel) => readFile(new URL(rel, import.meta.url), "utf8");

test("api types define the v5 match report, change ledger, and lineage fields", async () => {
  const source = await read("../lib/api-types.ts");
  assert.match(source, /export interface MatchReport/);
  assert.match(source, /original_ats_match: AtsMatchScore/);
  assert.match(source, /tailored_ats_match: AtsMatchScore \| null/);
  assert.match(source, /alignment_score: number/);
  assert.match(source, /export interface ChangeRecord/);
  assert.match(source, /change_ledger: ChangeRecord\[\]/);
  assert.match(source, /revision: number/);
  assert.match(source, /parent_kit_id: string \| null/);
});

test("match insights presents three distinct, labelled scores with a11y and a disclaimer", async () => {
  const source = await read("../components/product/match-insights.tsx");
  assert.match(source, /Original resume keyword match/);
  assert.match(source, /Tailored resume keyword match/);
  assert.match(source, /Evidence-based role alignment/);
  // Accessible text equivalents for the graphical meters.
  assert.match(source, /aria-label=\{`\$\{label\}: \$\{rounded\} out of 100`\}/);
  assert.match(source, /role="meter"/);
  assert.match(source, /report\.disclaimer/);
});

test("change ledger has accept/reject/restore, batch apply, and conflict/error states", async () => {
  const source = await read("../components/product/change-ledger.tsx");
  assert.match(source, /applyChangeActions/);
  assert.match(source, /"applying" \| "success" \| "error" \| "conflict"/);
  assert.match(source, /error\.status === 409/);
  // Irreversible records are locked, not rejectable.
  assert.match(source, /record\.reversible \?/);
  assert.match(source, /Locked/);
  assert.match(source, /revision \{revision\}/);
});

test("job fit no longer renders interview_probability as a percentage", async () => {
  const source = await read("../components/product/job-fit-workspace.tsx");
  assert.doesNotMatch(source, /interview_probability/);
  assert.doesNotMatch(source, /interview probability \$\{/);
});

test("scoring page explains the three scores and irreversible grounding removals", async () => {
  const source = await read("../app/scoring/page.tsx");
  assert.match(source, /Original resume keyword match/);
  assert.match(source, /Tailored resume keyword match/);
  assert.match(source, /Evidence-based role alignment/);
  assert.match(source, /grounding removals cannot be restored/i);
  assert.match(source, /never inserted into your resume/i);
});

test("unified workspace wires match insights, change ledger, and lineage; v5 is current", async () => {
  const source = await read("../components/product/unified-kit-workspace.tsx");
  assert.match(source, /MatchInsights/);
  assert.match(source, /ChangeLedger/);
  assert.match(source, /KitLineageActions/);
  assert.match(source, /application-kit\/v5/);
});
