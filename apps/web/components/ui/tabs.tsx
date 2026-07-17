"use client";

import { useRef, useState } from "react";

export type TabItem = { id: string; label: string; panel: string };

export function Tabs({ items, label }: { items: TabItem[]; label: string }) {
  const [selected, setSelected] = useState(items[0]?.id ?? "");
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function move(index: number, direction: number) {
    const next = (index + direction + items.length) % items.length;
    setSelected(items[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className="scrollbar-none flex overflow-x-auto border-b border-border">
        {items.map((item, index) => (
          <button
            key={item.id}
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${item.id}-tab`}
            aria-controls={`${item.id}-panel`}
            aria-selected={selected === item.id}
            tabIndex={selected === item.id ? 0 : -1}
            onClick={() => setSelected(item.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") move(index, 1);
              if (event.key === "ArrowLeft") move(index, -1);
              if (event.key === "Home") move(0, 0);
              if (event.key === "End") move(items.length - 1, 0);
            }}
            className="min-h-11 whitespace-nowrap border-b-2 border-transparent px-4 text-sm text-ink-muted aria-selected:border-accent aria-selected:font-semibold aria-selected:text-ink"
          >
            {item.label}
          </button>
        ))}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          id={`${item.id}-panel`}
          role="tabpanel"
          aria-labelledby={`${item.id}-tab`}
          hidden={selected !== item.id}
          className="rounded-b-md border border-t-0 border-border bg-surface p-4 text-sm text-ink-secondary"
        >
          {item.panel}
        </div>
      ))}
    </div>
  );
}
