import { cn } from "@/lib/utils";

export function StatusBadge({ status, className }: { status: "Pass" | "Fail" | "N/A"; className?: string }) {
  const map = {
    Pass: "bg-emerald-50 text-emerald-700 border-emerald-200",
    Fail: "bg-red-50 text-red-700 border-red-200",
    "N/A": "bg-slate-100 text-slate-600 border-slate-200",
  } as const;
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", map[status], className)}>
      {status}
    </span>
  );
}

export function ReviewedBadge({ reviewed }: { reviewed: boolean }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
      reviewed ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-amber-50 text-amber-700 border-amber-200",
    )}>
      {reviewed ? "Reviewed" : "Not Reviewed"}
    </span>
  );
}

export function CategoryTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600">
      {children}
    </span>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 pb-6 border-b border-slate-200">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
