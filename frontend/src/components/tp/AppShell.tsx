import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { LayoutDashboard, Upload, FileText, BookOpen, BarChart3, Settings, ShieldCheck } from "lucide-react";
import { useTP, useCurrentUser } from "@/lib/tp-context";
import { cn } from "@/lib/utils";

const NAV: Array<{ to: string; label: string; icon: typeof LayoutDashboard; exact?: boolean }> = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/upload", label: "Upload New", icon: Upload },
  { to: "/plans", label: "Treatment Plans", icon: FileText },
  { to: "/rules", label: "Rules Studio", icon: BookOpen },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/admin", label: "Admin Settings", icon: Settings },
];

export function AppShell() {
  const { role, setRole } = useTP();
  const user = useCurrentUser();
  const pathname = useRouterState({ select: s => s.location.pathname });

  return (
    <div className="min-h-screen h-screen flex bg-slate-50 text-slate-900">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-slate-200 bg-white flex flex-col">
        <div className="h-14 flex items-center gap-2 px-4 border-b border-slate-200">
          <div className="h-8 w-8 rounded-md bg-slate-900 text-white grid place-items-center">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">BrightPath</div>
            <div className="text-[11px] text-slate-500 leading-tight">TP Review</div>
          </div>
        </div>
        <nav className="p-2 space-y-0.5 flex-1">
          {NAV.map(item => {
            const active = item.exact ? pathname === item.to : pathname.startsWith(item.to) && item.to !== "/";
            const restricted = item.to === "/admin" && role !== "Admin";
            return (
              <Link
                key={item.to}
                to={item.to as string}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100",
                )}
              >
                <item.icon className="h-4 w-4" />
                <span className="flex-1">{item.label}</span>
                {restricted && <span className="text-[10px] uppercase tracking-wide opacity-70">read-only</span>}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-200 text-[11px] text-slate-500">
          v2026.07 · Compliance build
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 min-w-0 flex flex-col h-screen">
        <header className="h-14 shrink-0 border-b border-slate-200 bg-white flex items-center justify-between px-6 gap-4">
          <div className="text-sm text-slate-500">Insurance Compliance Review</div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5 rounded-md border border-slate-200 p-0.5 text-xs">
              <span className="pl-2 text-slate-500">View as:</span>
              {(["Admin", "Standard User"] as const).map(r => (
                <button
                  key={r}
                  onClick={() => setRole(r)}
                  className={cn(
                    "px-2.5 py-1 rounded transition-colors",
                    role === r ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
                  )}
                >{r}</button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-slate-200 grid place-items-center text-xs font-semibold text-slate-700">
                {user.name.split(" ").map(n => n[0]).join("")}
              </div>
              <div className="text-xs leading-tight">
                <div className="font-medium">{user.name}, {user.credentials}</div>
                <div className="text-slate-500">Clinical Director</div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 min-h-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
