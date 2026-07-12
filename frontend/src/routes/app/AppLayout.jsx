import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { clearCustomerToken } from "../../lib/auth";

export default function AppLayout() {
  const nav = useNavigate();
  const loc = useLocation();
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const data = await api.me();
      setMe(data);
    } catch {
      clearCustomerToken();
      nav("/app/login", { replace: true });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Force profile completion before using the app.
  useEffect(() => {
    if (me && !me.profile_complete && !loc.pathname.startsWith("/app/profile")) {
      nav("/app/profile", { replace: true });
    }
  }, [me, loc.pathname, nav]);

  const logout = () => {
    clearCustomerToken();
    nav("/app/login", { replace: true });
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center text-brand">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-gray-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/app" className="text-sm font-semibold text-navy">
            Claims Portal
          </Link>
          <div className="flex items-center gap-4 text-sm">
            {me?.member_id && (
              <span className="hidden text-gray-400 sm:inline">{me.member_id}</span>
            )}
            {me?.full_name && <span className="text-navy">{me.full_name}</span>}
            <button onClick={logout} className="text-gray-400 hover:text-navy">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet context={{ me, reloadMe: load }} />
      </main>
    </div>
  );
}
