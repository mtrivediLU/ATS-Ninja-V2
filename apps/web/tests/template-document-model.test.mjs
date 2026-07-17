import assert from "node:assert/strict";
import test from "node:test";
import { buildDocumentModel, documentText, paginateDocument } from "../components/product/templates/document-model.ts";
import { templateFilename } from "../lib/product.ts";

const resume = `Avery Candidate
avery@example.test · Toronto, ON

SUMMARY
Evidence-grounded product engineer.

EXPERIENCE
Example Co. — Engineer
• Built a deterministic workflow.

SKILLS
TypeScript
Python

EDUCATION
Example University`;

test("recognizes only standalone approved resume headings and preserves every source character", () => {
  const model = buildDocumentModel("resume", resume);
  assert.equal(model.tier, 3);
  assert.equal(documentText(model), resume);
  if (model.tier === 3) {
    assert.deepEqual(model.sections.map((section) => section.heading), ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"]);
    assert.equal(model.sections[1].lines[1], "• Built a deterministic workflow.");
  }
});

test("uses the closed verbatim fallback for ambiguous resume text and every cover letter", () => {
  const tabular = buildDocumentModel("resume", "SUMMARY\nA concise profile\nExperience | Company | Dates");
  const letter = buildDocumentModel("cover-letter", "Dear Hiring Team,\n\nI am writing to apply.");
  assert.equal(tabular.tier, 4);
  assert.equal(letter.tier, 4);
  assert.equal(documentText(tabular), "SUMMARY\nA concise profile\nExperience | Company | Dates");
  assert.equal(documentText(letter), "Dear Hiring Team,\n\nI am writing to apply.");
});

test("paginates sections deterministically without splitting or changing their order", () => {
  const model = buildDocumentModel("resume", resume);
  assert.equal(model.tier, 3);
  const pages = paginateDocument(model, "comfortable");
  const headings = pages.flatMap((page) => page.kind === "structured" ? page.sections.map((section) => section.heading) : []);
  assert.deepEqual(headings, ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"]);
  assert.equal(pages[0].kind, "structured");
  if (pages[0].kind === "structured") assert.deepEqual(pages[0].headerLines, ["Avery Candidate", "avery@example.test · Toronto, ON", ""]);
});

test("template filenames omit unavailable target placeholders and retain the chosen template", () => {
  assert.equal(templateFilename("Target company unavailable", "Application kit", "resume", "classic"), "resume-classic-ats");
  assert.equal(templateFilename("Northwind Labs", "Product Engineer", "cover-letter", "modern"), "northwind-labs-product-engineer-cover-letter-modern-ats");
});
