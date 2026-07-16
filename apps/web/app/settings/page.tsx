import type { Metadata } from "next";
import { Banner, Card, Field, Select, Switch } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Local settings" };

export default function SettingsPage() {
  return (
    <div className="space-y-5">
      <Banner tone="neutral" title="Foundation preferences only.">Controls are illustrative and are not currently persisted. Light is the only approved D0 theme.</Banner>
      <Card>
        <h2 className="text-md font-semibold">Defaults for new kits</h2>
        <div className="mt-3 grid gap-2"><Switch id="settings-fit" label="Generate job-fit analysis by default" defaultChecked /><Switch id="settings-interview" label="Generate interview preparation by default" defaultChecked /><Switch id="settings-outreach" label="Generate LinkedIn outreach drafts by default" /></div>
      </Card>
      <Card>
        <h2 className="text-md font-semibold">Appearance</h2>
        <p className="mt-1 text-sm text-ink-secondary">The token structure is ready for later theming; dark mode is not implemented in D0.</p>
        <Field label="Theme" htmlFor="settings-theme" hint="Only the approved light theme is available." className="mt-4 max-w-sm"><Select id="settings-theme" disabled defaultValue="light" aria-describedby="settings-theme-description"><option value="light">Signal light</option></Select></Field>
      </Card>
    </div>
  );
}
