"use client";

import { useCallback, useEffect, useState } from "react";

export type LocalTextEditor = {
  editing: boolean;
  draft: string;
  applied: string;
  dirty: boolean;
  edited: boolean;
  beginEdit: () => void;
  setDraft: (text: string) => void;
  apply: () => boolean;
  discard: () => void;
  exit: () => boolean;
  reset: () => void;
};

/**
 * Session-only editor state. It intentionally has no browser-storage or API
 * integration; a page reload restores the generated server text.
 */
export function useLocalTextEditor(generated: string): LocalTextEditor {
  const [editing, setEditing] = useState(false);
  const [applied, setApplied] = useState(generated);
  const [draft, setDraft] = useState(generated);

  useEffect(() => {
    setEditing(false);
    setApplied(generated);
    setDraft(generated);
  }, [generated]);

  const dirty = draft !== applied;
  const edited = applied !== generated;
  const beginEdit = useCallback(() => { setDraft(applied); setEditing(true); }, [applied]);
  const apply = useCallback(() => {
    if (!draft.trim()) return false;
    setApplied(draft);
    setEditing(false);
    return true;
  }, [draft]);
  const discard = useCallback(() => { setDraft(applied); setEditing(false); }, [applied]);
  const exit = useCallback(() => {
    if (draft !== applied) return false;
    setEditing(false);
    return true;
  }, [applied, draft]);
  const reset = useCallback(() => { setApplied(generated); setDraft(generated); setEditing(false); }, [generated]);
  return { editing, draft, applied, dirty, edited, beginEdit, setDraft, apply, discard, exit, reset };
}

/** Warn only while there are genuinely un-applied text changes. */
export function useUnsavedChangeProtection(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onDocumentClick = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement | null)?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (!window.confirm("Discard unsaved local edits and leave this page?")) event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onDocumentClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onDocumentClick, true);
    };
  }, [dirty]);
}
