import type { Metadata } from "next";
import { KitOverview } from "@/components/product/kit-overview";
import { KitStateBoundary } from "@/components/product/kit-state";

export const metadata: Metadata = { title: "Kit overview" };

export default function KitPage() {
  return <KitStateBoundary><KitOverview /></KitStateBoundary>;
}
