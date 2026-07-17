export type TemplateId = "classic" | "modern";
export type TemplateArtifact = "resume" | "cover-letter";

export type TemplateDefinition = {
  id: TemplateId;
  name: string;
  description: string;
  artifactTypes: readonly TemplateArtifact[];
  atsSafe: true;
  density: "compact" | "comfortable";
  printClass: "t1-classic" | "t1-modern";
  preview: { headerAlignment: "center" | "left"; accent: "ink" | "evergreen" };
  exportFormats: readonly ("print" | "txt" | "tex")[];
};

export const templateDefinitions: readonly TemplateDefinition[] = [
  {
    id: "classic",
    name: "Classic ATS",
    description: "Compact, conservative single-column layout with traditional serif typography.",
    artifactTypes: ["resume", "cover-letter"],
    atsSafe: true,
    density: "compact",
    printClass: "t1-classic",
    preview: { headerAlignment: "center", accent: "ink" },
    exportFormats: ["print", "txt", "tex"],
  },
  {
    id: "modern",
    name: "Modern ATS",
    description: "More whitespace with restrained evergreen accents in a single-column layout.",
    artifactTypes: ["resume", "cover-letter"],
    atsSafe: true,
    density: "comfortable",
    printClass: "t1-modern",
    preview: { headerAlignment: "left", accent: "evergreen" },
    exportFormats: ["print", "txt", "tex"],
  },
] as const;

export function templatesForArtifact(artifact: TemplateArtifact): readonly TemplateDefinition[] {
  return templateDefinitions.filter((template) => template.artifactTypes.includes(artifact));
}

export function templateById(id: TemplateId): TemplateDefinition {
  const template = templateDefinitions.find((candidate) => candidate.id === id);
  if (!template) throw new Error(`Unknown document template: ${id}`);
  return template;
}
