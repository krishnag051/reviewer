import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { configureApiClient, getMe, login as apiLogin, type Me } from "./api-client";

const TOKEN_STORAGE_KEY = "tp_review_token";

type AuthState = {
  // undefined = "haven't checked storage/backend yet" (initial load in
  // flight) -- distinct from null ("checked, definitely logged out"), so
  // route guards can show a brief loading state instead of flashing the
  // login screen for an already-logged-in user on every page refresh.
  user: Me | null | undefined;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null | undefined>(undefined);

  const logout = useCallback(() => {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    setUser(null);
  }, []);

  useEffect(() => {
    configureApiClient({
      getToken: () => window.localStorage.getItem(TOKEN_STORAGE_KEY),
      // A 401 from any real API call (expired/invalid token) always means
      // "you're not actually logged in" -- clear it and drop back to null
      // so the route guard redirects to /login, rather than the app
      // silently limping along on a token the backend no longer honors.
      onUnauthorized: () => {
        window.localStorage.removeItem(TOKEN_STORAGE_KEY);
        setUser(null);
      },
    });
  }, []);

  useEffect(() => {
    const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!token) { setUser(null); return; }
    getMe()
      .then(me => setUser(me))
      .catch(() => { window.localStorage.removeItem(TOKEN_STORAGE_KEY); setUser(null); });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await apiLogin(email, password);
    window.localStorage.setItem(TOKEN_STORAGE_KEY, access_token);
    const me = await getMe();
    setUser(me);
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("AuthProvider missing");
  return ctx;
}
