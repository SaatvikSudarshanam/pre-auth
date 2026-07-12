import { Navigate, Route, Routes } from "react-router-dom";

import { getAdminToken } from "../../lib/auth";
import AdminLayout from "./AdminLayout";
import AdminLogin from "./AdminLogin";
import ClaimReview from "./ClaimReview";
import Queue from "./Queue";

function AdminGuard({ children }) {
  return getAdminToken() ? children : <Navigate to="/admin/login" replace />;
}

export default function AdminApp() {
  return (
    <Routes>
      <Route path="login" element={<AdminLogin />} />
      <Route
        path=""
        element={
          <AdminGuard>
            <AdminLayout />
          </AdminGuard>
        }
      >
        <Route index element={<Queue />} />
        <Route path="claims/:id" element={<ClaimReview />} />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  );
}
