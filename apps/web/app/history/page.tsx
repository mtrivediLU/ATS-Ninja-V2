import type { Metadata } from "next";
import { HistoryWorkspace } from "@/components/product/history-workspace";

export const metadata: Metadata = { title: "Kit history" };

export default function HistoryPage() { return <HistoryWorkspace />; }
