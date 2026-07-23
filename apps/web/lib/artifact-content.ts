import type { AnswerArtifact, OutreachDraft } from "@/lib/api-types";

/** Presentation/export text only; candidate facts remain returned API values. */
export function formatAnswersText(artifact: AnswerArtifact): string {
  const text = artifact.items.map((item) => `${item.question}\n${item.answer}`).join("\n\n");
  return text || artifact.text;
}

/** The engine returns outreach drafts in recommendation order. Never invent one. */
export function recommendedOutreachDraft(drafts: OutreachDraft[]): OutreachDraft | null {
  return drafts[0] ?? null;
}
