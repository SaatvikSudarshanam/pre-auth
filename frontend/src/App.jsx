import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import ConsentBanner from "./components/ConsentBanner";
import { Spinner } from "./components/ui";
import { getCustomerToken } from "./lib/auth";
import Cookies from "./routes/Cookies";
import Landing from "./routes/Landing";
import Privacy from "./routes/Privacy";
import AppLayout from "./routes/app/AppLayout";
import ClaimDetail from "./routes/app/ClaimDetail";
import CompleteProfile from "./routes/app/CompleteProfile";
import Dashboard from "./routes/app/Dashboard";
import Login from "./routes/app/Login";
import NewClaim from "./routes/app/NewClaim";
import OAuthCallback from "./routes/app/OAuthCallback";

// Admin tree is lazy-loaded. Everything AI-related lives behind this dynamic
// import, so the customer never downloads the admin chunk (LLM isolation).
const AdminApp = lazy(() => import("./routes/admin/AdminApp"));

function CustomerGuard({ children }) {
  return getCustomerToken() ? children : <Navigate to="/app/login" replace />;
}

function FullSpinner() {
  return (
    <div className="flex h-screen items-center justify-center text-brand">
      <Spinner className="h-6 w-6" />
    </div>
  );
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/cookies" element={<Cookies />} />

        <Route path="/app/login" element={<Login />} />
        {/* OAuth return target — public, sets the token then redirects. */}
        <Route path="/app/oauth" element={<OAuthCallback />} />

        <Route
          path="/app"
          element={
            <CustomerGuard>
              <AppLayout />
            </CustomerGuard>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="new" element={<NewClaim />} />
          <Route path="claims/:id" element={<ClaimDetail />} />
          <Route path="profile" element={<CompleteProfile />} />
        </Route>

        <Route
          path="/admin/*"
          element={
            <Suspense fallback={<FullSpinner />}>
              <AdminApp />
            </Suspense>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ConsentBanner />
    </>
  );
}
