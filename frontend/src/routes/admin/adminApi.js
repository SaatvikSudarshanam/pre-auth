// Admin API surface — imported ONLY by the lazy-loaded admin chunk. This is the
// only frontend module that references AI endpoints.
import { getAdminToken } from "../../lib/auth";
import { request } from "../../lib/http";

const withAuth = (opts = {}) => ({ ...opts, token: getAdminToken() });

export const adminApi = {
  login: (username, password) =>
    request("/api/auth/admin/login", { method: "POST", body: { username, password } }),

  listClaims: (status) =>
    request(`/api/admin/claims${status ? `?status=${encodeURIComponent(status)}` : ""}`, withAuth()),
  getClaim: (id) => request(`/api/admin/claims/${id}`, withAuth()),
  stats: () => request("/api/admin/stats", withAuth()),

  runAiReview: (id) =>
    request(`/api/admin/claims/${id}/ai-review`, withAuth({ method: "POST" })),
  decide: (id, payload) =>
    request(`/api/admin/claims/${id}/decision`, withAuth({ method: "POST", body: payload })),
  notifyCall: (id, payload) =>
    request(`/api/admin/claims/${id}/notify-call`, withAuth({ method: "POST", body: payload })),
};

// Documents are guarded, so we fetch them with the bearer token and hand back an
// object URL the viewer can render inline.
export async function documentObjectUrl(id) {
  const res = await fetch(`/api/admin/documents/${id}`, {
    headers: { Authorization: `Bearer ${getAdminToken()}` },
  });
  if (!res.ok) throw new Error("Could not load document");
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type };
}
