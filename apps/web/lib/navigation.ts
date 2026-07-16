import type { LucideIcon } from "lucide-react";
import {
  BriefcaseBusiness,
  FileText,
  History,
  LayoutGrid,
  ListChecks,
  Mail,
  MessageSquareText,
  Mic2,
  Plus,
  Settings2,
  ShieldCheck,
  Target,
} from "lucide-react";

export const artifactSlugs = [
  "resume",
  "cover-letter",
  "answers",
  "job-fit",
  "interview-prep",
  "linkedin-outreach",
] as const;

export type ArtifactSlug = (typeof artifactSlugs)[number];

export type NavigationItem = {
  id: string;
  label: string;
  shortLabel?: string;
  href?: string;
  icon: LucideIcon;
  primary?: boolean;
  currentKitOnly?: boolean;
  action?: "evidence" | "more";
  count?: number;
};

export type NavigationGroup = {
  id: "primary" | "current-kit" | "utility";
  label?: string;
  items: NavigationItem[];
};

export const artifactNavigation: ReadonlyArray<NavigationItem & { id: ArtifactSlug }> = [
  { id: "resume", label: "Resume", icon: FileText, currentKitOnly: true },
  { id: "cover-letter", label: "Cover letter", icon: Mail, currentKitOnly: true },
  { id: "answers", label: "Application answers", icon: ListChecks, currentKitOnly: true },
  { id: "job-fit", label: "Job fit", icon: Target, currentKitOnly: true },
  { id: "interview-prep", label: "Interview prep", icon: Mic2, currentKitOnly: true },
  {
    id: "linkedin-outreach",
    label: "LinkedIn outreach",
    icon: MessageSquareText,
    currentKitOnly: true,
  },
];

export function navigationGroups(hasCurrentKit: boolean, kitId = "demo"): NavigationGroup[] {
  return [
    {
      id: "primary",
      items: [
        { id: "new", label: "New Kit", shortLabel: "New", href: "/", icon: Plus, primary: true },
        { id: "history", label: "Kit history", shortLabel: "History", href: "/history", icon: History, count: 4 },
      ],
    },
    {
      id: "current-kit",
      label: "Current kit",
      items: [
        ...artifactNavigation.map((item) => ({
          ...item,
          href: hasCurrentKit ? `/kits/${kitId}/${item.id}` : undefined,
        })),
        {
          id: "evidence",
          label: "Evidence",
          icon: ShieldCheck,
          action: "evidence" as const,
          currentKitOnly: true,
        },
      ],
    },
    {
      id: "utility",
      items: [
        { id: "components", label: "Components", href: "/components", icon: LayoutGrid },
        { id: "settings", label: "Local settings", href: "/settings", icon: Settings2 },
      ],
    },
  ];
}

export const mobileMoreItem: NavigationItem = {
  id: "more",
  label: "More",
  shortLabel: "More",
  icon: BriefcaseBusiness,
  action: "more",
};
