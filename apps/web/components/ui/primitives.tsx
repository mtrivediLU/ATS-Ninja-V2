import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { forwardRef } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Check, FilePlus2, Info, LoaderCircle, OctagonAlert } from "lucide-react";
import type { StatusPresentation, StatusTone } from "@/lib/status";

function join(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "border-accent bg-accent text-on-accent hover:border-accent-hover hover:bg-accent-hover active:border-accent-active active:bg-accent-active",
  secondary: "border-border-strong bg-surface text-ink hover:bg-surface-subtle active:bg-surface-raised",
  ghost: "border-transparent bg-transparent text-ink-secondary hover:bg-surface-subtle hover:text-ink active:bg-surface-raised",
  destructive: "border-danger-border bg-surface text-danger hover:bg-danger-bg active:bg-danger-bg",
};

export function buttonClassName(variant: ButtonVariant = "secondary", size: "default" | "sm" = "default") {
  return join(
    "inline-flex items-center justify-center gap-2 rounded-control border font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50",
    size === "default" ? "min-h-11 px-4 py-2 text-base sm:min-h-10" : "min-h-11 px-3 py-1 text-sm sm:min-h-8",
    buttonVariants[variant],
  );
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "default" | "sm";
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "secondary", size = "default", type = "button", ...props },
  ref,
) {
  return <button ref={ref} type={type} className={join(buttonClassName(variant, size), className)} {...props} />;
});

export const IconButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function IconButton({ className, type = "button", ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={join(
          "grid size-11 shrink-0 place-items-center rounded-control border border-border bg-surface text-ink-secondary transition-colors hover:bg-surface-subtle hover:text-ink active:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50 sm:size-10",
          className,
        )}
        {...props}
      />
    );
  },
);

type FieldProps = {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
};

export function Field({ label, htmlFor, hint, error, children, className }: FieldProps) {
  const descriptionId = `${htmlFor}-description`;
  return (
    <div className={join("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm font-semibold text-ink-secondary">
        {label}
      </label>
      {children}
      {(error || hint) && (
        <p id={descriptionId} className={join("m-0 text-xs", error ? "text-danger" : "text-ink-muted")}>
          {error ? `Error: ${error}` : hint}
        </p>
      )}
    </div>
  );
}

const controlClass =
  "w-full rounded-control border border-border-strong bg-surface px-3 py-2.5 text-base text-ink placeholder:text-ink-faint transition-[border-color,box-shadow] duration-150 focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent-subtle disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:text-ink-muted aria-invalid:border-danger-border aria-invalid:ring-danger-bg";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={join(controlClass, className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={join(controlClass, "min-h-30 resize-y leading-relaxed", className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...props },
  ref,
) {
  return <select ref={ref} className={join(controlClass, className)} {...props} />;
});

export function Switch({ id, label, defaultChecked = false, disabled = false }: { id: string; label: string; defaultChecked?: boolean; disabled?: boolean }) {
  return (
    <label htmlFor={id} className={join("inline-flex min-h-11 items-center gap-3 text-base sm:min-h-10", disabled && "opacity-50")}>
      <span className="relative inline-flex shrink-0">
        <input id={id} type="checkbox" role="switch" className="peer sr-only" defaultChecked={defaultChecked} disabled={disabled} />
        <span className="h-[22px] w-10 rounded-pill bg-border-strong transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent peer-disabled:cursor-not-allowed" />
        <span className="pointer-events-none absolute left-0.5 top-0.5 size-[18px] rounded-pill bg-surface shadow-xs transition-transform peer-checked:translate-x-[18px]" />
      </span>
      <span>{label}</span>
    </label>
  );
}

export function Checkbox({ id, label, defaultChecked = false, disabled = false }: { id: string; label: string; defaultChecked?: boolean; disabled?: boolean }) {
  return (
    <label htmlFor={id} className={join("inline-flex min-h-11 items-center gap-2 text-base sm:min-h-10", disabled && "opacity-50")}>
      <input
        id={id}
        type="checkbox"
        defaultChecked={defaultChecked}
        disabled={disabled}
        className="size-5 rounded-sm border-border-strong accent-accent"
      />
      <span>{label}</span>
    </label>
  );
}

const statusClasses: Record<StatusTone, string> = {
  positive: "border-positive-border bg-positive-bg text-positive",
  warning: "border-warning-border bg-warning-bg text-warning",
  danger: "border-danger-border bg-danger-bg text-danger",
  info: "border-info-border bg-info-bg text-info",
  neutral: "border-neutral-border bg-neutral-bg text-neutral",
  edited: "border-edited-border bg-edited-bg text-edited",
  unavailable: "border-unavailable-border border-dashed bg-unavailable-bg text-unavailable",
};

export function Badge({ tone = "neutral", children, className }: { tone?: StatusTone; children: ReactNode; className?: string }) {
  return (
    <span className={join("inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 text-xs font-semibold", statusClasses[tone], className)}>
      {children}
    </span>
  );
}

export function StatusLabel({ presentation, className }: { presentation: StatusPresentation; className?: string }) {
  const Icon = presentation.icon;
  return (
    <Badge tone={presentation.tone} className={className}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />
      <span aria-label={presentation.accessibleLabel}>{presentation.label}</span>
    </Badge>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={join("rounded-lg border border-border bg-surface p-5 shadow-sm", className)} {...props} />;
}

export function Section({ title, description, children, className }: { title: string; description?: string; children: ReactNode; className?: string }) {
  return (
    <section className={join("space-y-3", className)}>
      <div>
        <h2 className="m-0 text-md font-semibold leading-tight">{title}</h2>
        {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

const bannerConfig = {
  info: { classes: "border-info-border bg-info-bg text-info", icon: Info },
  warning: { classes: "border-warning-border bg-warning-bg text-warning", icon: AlertTriangle },
  neutral: { classes: "border-border bg-surface-subtle text-ink-secondary", icon: Info },
  danger: { classes: "border-danger-border bg-danger-bg text-danger", icon: OctagonAlert },
} as const;

export function Banner({ tone = "neutral", title, children, className }: { tone?: keyof typeof bannerConfig; title?: string; children: ReactNode; className?: string }) {
  const config = bannerConfig[tone];
  const Icon = config.icon;
  return (
    <div className={join("flex items-start gap-3 rounded-md border px-4 py-3 text-sm", config.classes, className)} role={tone === "danger" ? "alert" : undefined}>
      <Icon aria-hidden="true" className="mt-0.5 size-[18px] shrink-0" strokeWidth={1.8} />
      <div className="min-w-0 text-pretty">
        {title && <strong className="font-semibold">{title} </strong>}
        {children}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={join("block h-2.5 rounded-sm bg-border-subtle", className)} />;
}

export function PlaceholderBlock({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong bg-surface-subtle p-5">
      <p className="mb-4 font-mono text-xs font-medium uppercase tracking-[0.04em] text-ink-muted">{label}</p>
      <div className="space-y-2">
        <Skeleton className="w-2/5" />
        <Skeleton />
        <Skeleton className="w-11/12" />
        <Skeleton className="w-3/4" />
      </div>
    </div>
  );
}

export function EmptyState({ title, description, action, icon: Icon = FilePlus2 }: { title: string; description: string; action?: ReactNode; icon?: LucideIcon }) {
  return (
    <div className="mx-auto flex max-w-[480px] flex-col items-center py-12 text-center sm:py-16">
      <div className="mb-5 grid size-[72px] place-items-center rounded-lg border border-accent-border bg-accent-subtle text-accent">
        <Icon aria-hidden="true" className="size-9" strokeWidth={1.5} />
      </div>
      <h2 className="text-xl font-bold leading-tight tracking-[-0.01em]">{title}</h2>
      <p className="mt-3 text-pretty text-base text-ink-secondary">{description}</p>
      {action && <div className="mt-5 flex flex-wrap justify-center gap-3">{action}</div>}
    </div>
  );
}

export type ProcessingStep = { label: string; state: "done" | "active" | "pending" };

export function ProcessingState({ title, description, steps, slow = false }: { title: string; description: string; steps: ProcessingStep[]; slow?: boolean }) {
  return (
    <section className="mx-auto max-w-[580px] py-8" aria-live="polite" aria-busy="true">
      <h2 className="text-lg font-semibold leading-tight">{title}</h2>
      <p className="mt-2 text-pretty text-base text-ink-secondary">{description}</p>
      {slow && <Banner tone="info" className="mt-4" title="Still working.">Large kits can take longer. The worker keeps processing safely in the background.</Banner>}
      <ol className="mt-5 space-y-3">
        {steps.map((step) => (
          <li
            key={step.label}
            className={join(
              "flex min-h-12 items-center gap-3 rounded-md border px-4 py-3 text-sm",
              step.state === "active" ? "border-info-border bg-info-bg" : "border-border bg-surface",
              step.state === "pending" && "text-ink-muted",
            )}
          >
            <span className={join("grid size-[22px] shrink-0 place-items-center rounded-pill border-2", step.state === "done" ? "border-positive bg-positive text-on-accent" : step.state === "active" ? "border-info text-info" : "border-border-strong")}>
              {step.state === "done" && <Check aria-hidden="true" className="size-3" />}
              {step.state === "active" && <LoaderCircle aria-hidden="true" className="size-3.5 motion-safe:animate-spin" />}
            </span>
            <span>{step.label}</span>
            <span className="sr-only">{step.state}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ErrorState({ title, description, status, action }: { title: string; description: string; status: StatusPresentation; action?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-[500px] flex-col items-center py-12 text-center" role="alert">
      <div className="mb-4 grid size-16 place-items-center rounded-lg border border-danger-border bg-danger-bg text-danger">
        <OctagonAlert aria-hidden="true" className="size-7" />
      </div>
      <h2 className="text-lg font-semibold leading-tight">{title}</h2>
      <p className="mt-2 text-pretty text-base text-ink-secondary">{description}</p>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
        <StatusLabel presentation={status} />
        {action}
      </div>
    </div>
  );
}

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex min-w-0">
      {children}
      <span role="tooltip" className="pointer-events-none absolute bottom-[calc(100%+8px)] right-0 z-[var(--z-tooltip)] translate-y-1 whitespace-nowrap rounded-sm bg-ink px-2.5 py-1.5 text-xs text-surface opacity-0 shadow-md transition-[opacity,transform] group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:translate-y-0 group-focus-within:opacity-100">
        {label}
      </span>
    </span>
  );
}
