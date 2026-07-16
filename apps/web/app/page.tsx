import type { Metadata } from "next";
import { NewKitFoundation } from "@/components/foundation/new-kit-foundation";

export const metadata: Metadata = { title: "New Kit" };

export default function Home() {
  return <NewKitFoundation />;
}
