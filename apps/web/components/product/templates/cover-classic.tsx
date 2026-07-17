import { DocumentFallback } from "@/components/product/templates/document-fallback";

export function CoverClassic({ text, reason }: { text: string; reason: string }) {
  return <div className="t1-cover t1-classic"><DocumentFallback text={text} reason={reason} /></div>;
}
