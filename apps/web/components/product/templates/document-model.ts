import type { TemplateArtifact } from "@/components/product/templates/template-definitions";

export type DocumentSection = {
  heading: string;
  lines: string[];
  kind: "skills" | "generic";
};

export type StructuredDocumentModel = {
  tier: 3;
  artifact: "resume";
  sourceText: string;
  headerLines: string[];
  sections: DocumentSection[];
};

export type VerbatimDocumentModel = {
  tier: 4;
  artifact: TemplateArtifact;
  sourceText: string;
  reason: string;
};

export type DocumentModel = StructuredDocumentModel | VerbatimDocumentModel;

export type DocumentPage =
  | { kind: "structured"; headerLines: string[]; sections: DocumentSection[] }
  | { kind: "verbatim"; text: string };

const headings = new Map<string, DocumentSection["kind"]>([
  ["summary", "generic"],
  ["professional summary", "generic"],
  ["objective", "generic"],
  ["experience", "generic"],
  ["work experience", "generic"],
  ["professional experience", "generic"],
  ["employment", "generic"],
  ["education", "generic"],
  ["skills", "skills"],
  ["technical skills", "skills"],
  ["core skills", "skills"],
  ["certifications", "generic"],
  ["licenses & certifications", "generic"],
  ["projects", "generic"],
  ["awards", "generic"],
  ["publications", "generic"],
  ["volunteer", "generic"],
  ["languages", "generic"],
]);

function normalizedHeading(line: string): string {
  return line.trim().replace(/:$/, "").toLowerCase();
}

export function recognizedHeading(line: string): DocumentSection["kind"] | null {
  if (line.trim() !== line && line.trim().length === 0) return null;
  return headings.get(normalizedHeading(line)) ?? null;
}

function lowConfidence(text: string, recognized: number): boolean {
  if (recognized === 0) return true;
  // Tables, columns, markdown heading syntax, and tab-delimited source are not
  // safe to reinterpret in a presentation template.
  return text.split(/\r?\n/).some((line) => /\t|^#{1,6}\s/.test(line) || (line.match(/\|/g)?.length ?? 0) > 1);
}

/**
 * Pure, intentionally narrow mapper. It recognises only standalone approved
 * headings and preserves every line in its original order. Anything ambiguous
 * uses the verbatim Tier 4 path instead of attempting a richer parse.
 */
export function buildDocumentModel(artifact: TemplateArtifact, sourceText: string): DocumentModel {
  if (artifact === "cover-letter") {
    return {
      tier: 4,
      artifact,
      sourceText,
      reason: "The current API does not provide structured recipient or letter fields, so the exact cover-letter wording is preserved verbatim.",
    };
  }

  const lines = sourceText.split(/\r?\n/);
  const recognized = lines.filter((line) => recognizedHeading(line) !== null).length;
  if (lowConfidence(sourceText, recognized)) {
    return {
      tier: 4,
      artifact,
      sourceText,
      reason: "Confident structured formatting was not available, so the exact generated wording is preserved verbatim.",
    };
  }

  const headerLines: string[] = [];
  const sections: DocumentSection[] = [];
  let current: DocumentSection | null = null;
  for (const line of lines) {
    const kind = recognizedHeading(line);
    if (kind) {
      current = { heading: line, lines: [], kind };
      sections.push(current);
    } else if (current) {
      current.lines.push(line);
    } else {
      headerLines.push(line);
    }
  }

  if (!sections.length) {
    return {
      tier: 4,
      artifact,
      sourceText,
      reason: "Confident structured formatting was not available, so the exact generated wording is preserved verbatim.",
    };
  }
  return { tier: 3, artifact, sourceText, headerLines, sections };
}

export function documentText(model: DocumentModel): string {
  return model.sourceText;
}

function sectionSize(section: DocumentSection): number {
  return Math.max(3, section.lines.length + 2);
}

/** Deterministic preview pages. A section is never split or reordered. */
export function paginateDocument(model: DocumentModel, density: "compact" | "comfortable"): DocumentPage[] {
  if (model.tier === 4) {
    const lines = model.sourceText.split(/\r?\n/);
    const pageLines = density === "compact" ? 58 : 50;
    const pages: DocumentPage[] = [];
    for (let index = 0; index < lines.length || (index === 0 && lines.length === 0); index += pageLines) {
      pages.push({ kind: "verbatim", text: lines.slice(index, index + pageLines).join("\n") });
    }
    return pages;
  }

  const budget = density === "compact" ? 57 : 49;
  const pages: DocumentPage[] = [];
  let current: DocumentSection[] = [];
  let used = model.headerLines.length + 3;
  for (const section of model.sections) {
    const size = sectionSize(section);
    if (current.length > 0 && used + size > budget) {
      pages.push({ kind: "structured", headerLines: pages.length === 0 ? model.headerLines : [], sections: current });
      current = [];
      used = 0;
    }
    current.push(section);
    used += size;
  }
  pages.push({ kind: "structured", headerLines: pages.length === 0 ? model.headerLines : [], sections: current });
  return pages;
}
