import { DocumentFallback } from "@/components/product/templates/document-fallback";

export function CoverModern({ text, reason }: { text: string; reason: string }) {
  return <div className="t1-cover t1-modern"><div className="t1-modern-letter-rule" /><DocumentFallback text={text} reason={reason} /></div>;
}
