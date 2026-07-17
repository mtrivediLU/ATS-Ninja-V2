import type { Metadata } from "next";
import { Copy, Info, Plus } from "lucide-react";
import { EvidenceCard } from "@/components/shell/evidence-panel";
import { FeedbackDemo } from "@/components/ui/feedback-demo";
import {
  Badge,
  Banner,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  IconButton,
  Input,
  PlaceholderBlock,
  ProcessingState,
  Section,
  Select,
  Skeleton,
  StatusLabel,
  Switch,
  Textarea,
  Tooltip,
} from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/tabs";
import { demoEvidence } from "@/lib/demo-data";
import { claimStatusPresentation, kitStatusPresentation, notRequestedPresentation, withheldPresentation } from "@/lib/status";

export const metadata: Metadata = { title: "Components" };

export default function ComponentsPage() {
  return (
    <div className="space-y-8">
      <Banner tone="neutral" title="D0 reference surface.">Components consume semantic Signal tokens and carry no product calculations.</Banner>

      <Section title="Buttons and icon controls" description="Default, hover, focus-visible, active, destructive, and disabled states are available.">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary"><Plus aria-hidden="true" className="size-[17px]" />Primary</Button>
          <Button>Secondary</Button><Button variant="ghost">Ghost</Button><Button variant="destructive">Destructive</Button><Button variant="primary" disabled>Disabled</Button>
          <Tooltip label="Copy synthetic content"><IconButton aria-label="Copy synthetic content"><Copy aria-hidden="true" className="size-5" /></IconButton></Tooltip>
        </div>
      </Section>

      <Section title="Form controls" description="Every control has a visible label and associated hint or error text.">
        <div className="grid gap-5 lg:grid-cols-2">
          <Field label="Text input" htmlFor="component-input" hint="A normal filled state."><Input id="component-input" aria-describedby="component-input-description" defaultValue="Synthetic value" /></Field>
          <Field label="Error input" htmlFor="component-error" error="Enter a valid demonstration value."><Input id="component-error" aria-invalid="true" aria-describedby="component-error-description" defaultValue="Needs attention" /></Field>
          <Field label="Textarea" htmlFor="component-textarea" hint="Vertical resize remains available."><Textarea id="component-textarea" aria-describedby="component-textarea-description" placeholder="Synthetic text…" /></Field>
          <Field label="Select" htmlFor="component-select" hint="No preference is persisted."><Select id="component-select" aria-describedby="component-select-description" defaultValue="balanced"><option value="balanced">Balanced</option><option value="deterministic">Deterministic only</option></Select></Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-5"><Switch id="component-switch" label="Switch on" defaultChecked /><Checkbox id="component-check" label="Checkbox selected" defaultChecked /><Switch id="component-disabled" label="Disabled" disabled /></div>
      </Section>

      <Section title="Tabs">
        <Tabs label="Foundation tab example" items={[{ id: "overview", label: "Overview", panel: "Arrow keys move between these presentation-only tabs." }, { id: "validation", label: "Validation", panel: "Validation values would be rendered from the API." }, { id: "evidence", label: "Evidence", panel: "Evidence fields remain bounded and source-labelled." }]} />
      </Section>

      <Section title="Badges and status labels" description="Every product status includes an icon and text; colour is secondary.">
        <div className="flex flex-wrap gap-2">
          <StatusLabel presentation={kitStatusPresentation.completed} /><StatusLabel presentation={kitStatusPresentation.processing} /><StatusLabel presentation={kitStatusPresentation.pending} /><StatusLabel presentation={kitStatusPresentation.failed} />
          <StatusLabel presentation={claimStatusPresentation.supported} /><StatusLabel presentation={claimStatusPresentation.repaired} /><StatusLabel presentation={claimStatusPresentation.rejected} /><StatusLabel presentation={notRequestedPresentation} /><StatusLabel presentation={withheldPresentation} />
          <Badge tone="neutral"><Info aria-hidden="true" className="size-3.5" />Neutral badge</Badge>
        </div>
      </Section>

      <Section title="Connected surfaces and banners">
        <Card className="space-y-3 shadow-none"><h3 className="font-semibold">One continuous surface</h3><div className="border-t border-border-subtle pt-3 text-sm text-ink-secondary">Related content is separated by hairlines instead of disconnected card grids.</div></Card>
        <div className="mt-3 space-y-3"><Banner tone="info" title="Information.">Deterministic path in use.</Banner><Banner tone="warning" title="Validation warning.">Two synthetic claims were adjusted.</Banner><Banner tone="danger" title="Withheld.">The artifact could not be generated safely.</Banner></div>
      </Section>

      <Section title="Evidence card foundation">
        <div className="max-w-md"><EvidenceCard record={demoEvidence[0]} /></div>
      </Section>

      <Section title="Loading, empty, and placeholder states">
        <div className="grid gap-4 xl:grid-cols-2">
          <Card><h3 className="mb-3 font-semibold">Skeleton</h3><div className="space-y-2"><Skeleton className="w-2/5" /><Skeleton /><Skeleton className="w-4/5" /></div></Card>
          <PlaceholderBlock label="Detailed artifact region — later design phase" />
        </div>
        <div className="mt-4 rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4"><EmptyState title="Nothing here yet" description="A compact intentional empty state, not an oversized void." /></div>
        <ProcessingState title="Processing demonstration" description="The active step is announced and shown with text plus shape." steps={[{ label: "Parse inputs", state: "done" }, { label: "Ground claims", state: "active" }, { label: "Assemble kit", state: "pending" }]} />
      </Section>

      <Section title="Dialog, tooltip, and toast" description="Dialog focus is trapped and restored; Escape closes it; the toast uses a polite live region."><FeedbackDemo /></Section>
    </div>
  );
}
