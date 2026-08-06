import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ShieldCheck, Eye, EyeOff } from "lucide-react";

export const Route = createFileRoute("/login")({ component: LoginPage });

// Real login against the real backend's POST /auth/login -- no public
// signup route exists or should exist here (CLAUDE.md's Auth invariant):
// accounts are admin-provisioned only, via POST /admin/users.
function LoginPage() {
  const { login, user } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Already logged in -- __root.tsx's AuthGate normally handles this
  // redirect, but guard here too in case this route is reached directly.
  if (user) {
    nav({ to: "/" });
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !password) { setError("Email and password are required."); return; }
    setSubmitting(true);
    try {
      await login(email, password);
      nav({ to: "/" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect email or password.");
      } else {
        setError(err instanceof Error ? err.message : "Login failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 justify-center mb-6">
          <div className="h-9 w-9 rounded-md bg-slate-900 text-white grid place-items-center">
            <ShieldCheck className="h-4.5 w-4.5" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">BrightPath</div>
            <div className="text-[11px] text-slate-500 leading-tight">TP Review</div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="rounded-lg border border-slate-200 bg-white p-6 space-y-4">
          <div>
            <h1 className="text-lg font-semibold">Sign in</h1>
            <p className="mt-1 text-sm text-slate-500">
              Accounts are provisioned by an administrator — there is no public sign-up.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email" type="email" autoComplete="username" value={email}
              onChange={e => setEmail(e.target.value)} placeholder="you@brightpath-aba.com"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password}
                onChange={e => setPassword(e.target.value)} className="pr-9"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
