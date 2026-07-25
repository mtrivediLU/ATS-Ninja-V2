import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { buildHeadline, scoreComparisonState } from "../lib/results-presentation.ts";

const read = (rel) => readFile(new URL(rel, import.meta.url), "utf8");

// --------------------------------------------------------------------------- //
// ResultsHeader: real pure-function tests for every documented fallback.
// --------------------------------------------------------------------------- //
test("headline: name, role, and company all present", () => {
  const headline = buildHeadline({ name: "Mihir", role: "IT Specialist", company: "Acme Co", hasRole: true, hasCompany: true });
  assert.equal(headline, "Hi Mihir, your Application Kit for the IT Specialist position at Acme Co is ready. All the best!");
});

test("headline: no candidate name detected", () => {
  const headline = buildHeadline({ name: "", role: "IT Specialist", company: "Acme Co", hasRole: true, hasCompany: true });
  assert.equal(headline, "Your Application Kit for the IT Specialist position at Acme Co is ready. All the best!");
});

test("headline: no company detected", () => {
  const headline = buildHeadline({ name: "Mihir", role: "IT Specialist", company: "", hasRole: true, hasCompany: false });
  assert.equal(headline, "Hi Mihir, your Application Kit for the IT Specialist position is ready. All the best!");
});

test("headline: no title detected", () => {
  const headline = buildHeadline({ name: "Mihir", role: "", company: "Acme Co", hasRole: false, hasCompany: true });
  assert.equal(headline, "Hi Mihir, your Application Kit for this position at Acme Co is ready. All the best!");
});

test("headline: neither role, company, nor name detected", () => {
  const headline = buildHeadline({ name: "", role: "", company: "", hasRole: false, hasCompany: false });
  assert.equal(headline, "Your Application Kit is ready.");
});

// --------------------------------------------------------------------------- //
// ScoreComparison: every honest score state, exercised as real function calls.
// --------------------------------------------------------------------------- //
test("score state: tailored higher than original", () => {
  const state = scoreComparisonState(51, 74);
  assert.equal(state.delta, 23);
  assert.equal(state.deltaLabel, "+23 points after evidence-backed tailoring");
  assert.equal(state.noteLabel, null);
  assert.match(state.srSummary, /Improved by 23 points\./);
});

test("score state: no score change", () => {
  const state = scoreComparisonState(42, 42);
  assert.equal(state.delta, 0);
  assert.equal(state.deltaLabel, "0 · No score change.");
  assert.equal(state.noteLabel, null);
  assert.match(state.srSummary, /No score change\./);
});

test("score state: lower after grounding removal", () => {
  const state = scoreComparisonState(58, 53);
  assert.equal(state.delta, -5);
  assert.equal(state.deltaLabel, "-5 points — unsupported content removed");
  assert.match(state.noteLabel ?? "", /more accurate, not weaker/);
  assert.match(state.srSummary, /Lower by 5 points\./);
});

test("score state: tailored unavailable (older kit / not requested)", () => {
  const state = scoreComparisonState(65, null);
  assert.equal(state.tailored, null);
  assert.equal(state.deltaLabel, null);
  assert.match(state.noteLabel ?? "", /only the original match is shown/);
  assert.match(state.srSummary, /A tailored resume was not produced/);
});

// --------------------------------------------------------------------------- //
// Structural requirements: the approved D4 hierarchy, source-inspected because
// the current stack has no component-rendering test runner (no jsdom/RTL).
// --------------------------------------------------------------------------- //
test("results page renders the seven-item D4 hierarchy in order, nothing extra", async () => {
  const source = await read("../components/product/unified-kit-workspace.tsx");
  // Match JSX usage sites specifically (`<Component`), not import statements,
  // since imports are alphabetized and would otherwise scramble the check.
  const order = ["<ResultsHeader", "<ScoreComparison", "<KeywordsAdded", "<JobPriorities", "<FitPanels", "downloads-heading", "<AdvancedDetails"];
  let cursor = -1;
  for (const marker of order) {
    const index = source.indexOf(marker);
    assert.ok(index > cursor, `expected "${marker}" to appear after the previous section`);
    cursor = index;
  }
  // The old, superseded large explanation card and requirement table must not
  // reappear on the main page.
  assert.doesNotMatch(source, /How we strengthened/i);
  assert.doesNotMatch(source, /requirement-assessment-table|RequirementTable/);
});

test("fit panels render exactly two categories, no nice-to-have or lower-priority", async () => {
  const source = await read("../components/product/fit-panels.tsx");
  assert.match(source, /Your strengths/);
  assert.match(source, /Gaps to be aware of/);
  assert.doesNotMatch(source, /nice.to.have/i);
  assert.doesNotMatch(source, /lower.priority/i);
  assert.match(source, /not your ability to learn or perform the work/);
});

test("keywords-added is compact, evidence-backed, and has an honest empty state", async () => {
  const source = await read("../components/product/keywords-added.tsx");
  assert.match(source, /keywords_surfaced_by_tailoring/);
  assert.match(source, /Only keywords supported by your existing experience were added/);
  assert.match(source, /No new evidence-backed keywords were added/);
  assert.doesNotMatch(source, /change_ledger|claim_id/i);
});

test("job priorities render natural-language bullets, not a requirement table", async () => {
  const source = await read("../components/product/job-priorities.tsx");
  assert.match(source, /job_priorities/);
  assert.doesNotMatch(source, /<table/i);
  assert.doesNotMatch(source, /evidenceState|evidence_tier/);
});

test("advanced details is the one quiet entry with correct aria wiring", async () => {
  const source = await read("../components/product/advanced-details.tsx");
  assert.match(source, /aria-expanded=\{open\}/);
  assert.match(source, /aria-controls=\{panelId\}/);
  assert.match(source, /View detailed analysis and evidence/);
  // Collapsed content must not render at all (not merely hidden via CSS), so
  // it is never exposed to assistive tech while closed.
  assert.match(source, /\{open && \(/);
});

test("format selector is a real radiogroup that relabels both downloads", async () => {
  const source = await read("../components/product/format-selector.tsx");
  assert.match(source, /role="radiogroup"/);
  assert.match(source, /role="radio"/);
  assert.match(source, /aria-checked=\{selected\}/);

  const download = await read("../components/product/quick-pdf-download.tsx");
  assert.match(download, /exportDocumentDocx/);
  assert.match(download, /exportDocumentPdf/);
  assert.match(download, /format === "word" \? "Word" : "PDF"/);
});

test("new kit submission lands on the results-first page, never a specific artifact", async () => {
  const source = await read("../components/product/new-kit-wizard.tsx");
  assert.match(source, /router\.push\(`\/kits\/\$\{kit\.id\}`\)/);
  assert.doesNotMatch(source, /router\.push\(`\/kits\/\$\{kit\.id\}\/resume`\)/);
});

test("history links open the same base kit route as a fresh submission", async () => {
  const source = await read("../components/product/history-workspace.tsx");
  assert.match(source, /href=\{`\/kits\/\$\{item\.id\}`\}/);
});

test("primary document card accepts a format prop and relabels its download button", async () => {
  const source = await read("../components/product/primary-document-card.tsx");
  assert.match(source, /format\s*=\s*"pdf"/);
  assert.match(source, /format === "word" \? "Word" : "PDF"/);
});

test("results page grid is responsive without a fixed/sticky mobile overlay", async () => {
  const source = await read("../components/product/unified-kit-workspace.tsx");
  assert.match(source, /md:grid-cols-2/);
  assert.doesNotMatch(source, /position:\s*fixed|className="[^"]*\bfixed\b/);
});

test("score comparison panels stack on mobile and pair up from sm breakpoint", async () => {
  const source = await read("../components/product/score-comparison.tsx");
  assert.match(source, /sm:grid-cols-2/);
});
