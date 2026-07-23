import type { LucideIcon } from "lucide-react";
import {
  BriefcaseBusiness,
  FileText,
  History,
  LayoutGrid,
  LayoutDashboard,
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

export function navigationGroups(hasCurrentKit: boolean, kitId?: string): NavigationGroup[] {
  return [
    {
      id: "primary",
      items: [
        { id: "new", label: "New Kit", shortLabel: "New", href: "/kits/new", icon: Plus, primary: true },
        { id: "history", label: "Kit history", shortLabel: "History", href: "/history", icon: History },
      ],
    },
    {
      id: "current-kit",
      label: "Current kit",
      items: [
        {
          id: "overview",
          label: "Application Kit",
          href: hasCurrentKit && kitId ? `/kits/${kitId}` : undefined,
          icon: LayoutDashboard,
          currentKitOnly: true,
        },
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
