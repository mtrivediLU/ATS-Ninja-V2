export function DocumentFallback({ text, reason }: { text: string; reason: string }) {
  return <div className="t1-fallback"><p className="t1-fallback-note">{reason}</p><pre>{text}</pre></div>;
}
