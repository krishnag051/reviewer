import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { LayoutDashboard, Upload, FileText, BookOpen, BarChart3, Settings, ShieldCheck, Bug, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const NAV: Array<{ to: string; label: string; icon: typeof LayoutDashboard; exact?: boolean; developerOnly?: boolean }> = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { to: "/upload", label: "Upload New", icon: Upload },
  { to: "/plans", label: "Treatment Plans", icon: FileText },
  { to: "/rules", label: "Rules Studio", icon: BookOpen },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/admin", label: "Admin Settings", icon: Settings },
  // Diagnostics, not part of the normal review workflow -- see dev.tsx.
  // Round 41: gated to the developer role, hidden from the nav entirely
  // for anyone else (the route itself also gates -- see dev.tsx -- this
  // is just the paired "don't show a link you can't use" UX, not a second
  // permission system).
  { to: "/dev", label: "Developer Mode", icon: Bug, developerOnly: true },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const pathname = useRouterState({ select: s => s.location.pathname });
  const nav = useNavigate();

  // /login renders its own full-screen layout -- no sidebar/header chrome.
  if (pathname === "/login") {
    return <Outlet />;
  }

  // AuthGate (in __root.tsx) already redirects to /login before this ever
  // renders with a null user, but guard here too rather than assume.
  if (!user) return null;

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
          {NAV.filter(item => !item.developerOnly || user.role === "developer").map(item => {
            const active = item.exact ? pathname === item.to : pathname.startsWith(item.to) && item.to !== "/";
            const restricted = item.to === "/admin" && user.role !== "admin";
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
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-full bg-slate-200 grid place-items-center text-xs font-semibold text-slate-700">
                {user.name.split(" ").map(n => n[0]).join("")}
              </div>
              <div className="text-xs leading-tight">
                <div className="font-medium">{user.name}</div>
                <div className="text-slate-500 capitalize">{user.role}{user.credential_title ? ` · ${user.credential_title}` : ""}</div>
              </div>
            </div>
            <button
              onClick={() => { logout(); nav({ to: "/login" }); }}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            >
              <LogOut className="h-3.5 w-3.5" />Log out
            </button>
          </div>
        </header>
        <main className="flex-1 min-h-0 overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
