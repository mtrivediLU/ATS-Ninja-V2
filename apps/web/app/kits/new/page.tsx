import type { Metadata } from "next";
import { NewKitWizard } from "@/components/product/new-kit-wizard";

export const metadata: Metadata = { title: "Create Kit" };

export default function NewKitPage() {
  return <NewKitWizard />;
}
