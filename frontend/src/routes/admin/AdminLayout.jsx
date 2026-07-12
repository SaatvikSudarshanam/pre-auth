import { Link, Outlet, useNavigate } from "react-router-dom";

import { clearAdminToken } from "../../lib/auth";

export default function AdminLayout() {
  const nav = useNavigate();
  const logout = () => {
    clearAdminToken();
    nav("/admin/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-30 border-b border-gray-200 bg-navy">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/admin" className="text-sm font-semibold text-white">
            Reviewer Console
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-white/50">admin</span>
            <button onClick={logout} className="text-white/70 hover:text-white">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
