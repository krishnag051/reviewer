import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRootRouteWithContext, useNavigate, useRouter, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { reportLovableError } from "../lib/lovable-error-reporting";
import { TPProvider } from "@/lib/tp-context";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/tp/AppShell";
import { Toaster } from "@/components/ui/sonner";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-slate-900">404</h1>
        <h2 className="mt-4 text-xl font-semibold">Page not found</h2>
        <p className="mt-2 text-sm text-slate-500">
          The page you're looking for doesn't exist.
        </p>
        <a href="/" className="mt-6 inline-block rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white">Go home</a>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  useEffect(() => { reportLovableError(error, { boundary: "tanstack_root_error_component" }); }, [error]);
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="mt-2 text-sm text-slate-500">{error.message}</p>
        <button
          onClick={() => { router.invalidate(); reset(); }}
          className="mt-6 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
        >Try again</button>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

// Real login is required for every route except /login itself. `user` is
// `undefined` while the initial "is there a valid stored token?" check
// (auth-context.tsx's getMe() call) is still in flight -- rendering
// nothing during that window avoids a flash of the login screen for an
// already-logged-in user on every page refresh.
function AuthGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = useRouterState({ select: s => s.location.pathname });
  const nav = useNavigate();

  useEffect(() => {
    if (user === undefined) return;
    if (user === null && pathname !== "/login") {
      nav({ to: "/login" });
    } else if (user && pathname === "/login") {
      nav({ to: "/" });
    }
  }, [user, pathname, nav]);

  if (user === undefined) {
    return <div className="min-h-screen grid place-items-center text-sm text-slate-500">Loading…</div>;
  }
  if (user === null && pathname !== "/login") {
    return null; // redirect effect above is about to fire
  }
  return <>{children}</>;
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TPProvider>
          <AuthGate>
            <AppShell />
          </AuthGate>
          <Toaster />
        </TPProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
