// Customer API surface. Deliberately contains NO admin or AI endpoints — the
// customer bundle never references the LLM.
import { getCustomerToken } from "./auth";
import { request } from "./http";

const withAuth = (opts = {}) => ({ ...opts, token: getCustomerToken() });

export const api = {
  // auth
  signup: (email, password) =>
    request("/api/auth/signup", { method: "POST", body: { email, password } }),
  login: (email, password) =>
    request("/api/auth/login", { method: "POST", body: { email, password } }),
  googleLoginUrl: () => request("/api/auth/google/login-url"),

  // consent / policies (public)
  getPolicies: () => request("/api/policies"),
  recordConsent: (payload) =>
    request("/api/consent", withAuth({ method: "POST", body: payload })),

  // profile
  me: () => request("/api/me", withAuth()),
  completeProfile: (payload) =>
    request("/api/me/profile", withAuth({ method: "POST", body: payload })),
  listPlans: () => request("/api/plans", withAuth()),

  // claims
  listClaims: () => request("/api/claims", withAuth()),
  getClaim: (id) => request(`/api/claims/${id}`, withAuth()),
  createClaim: (payload) =>
    request("/api/claims", withAuth({ method: "POST", body: payload })),
  completeness: (id) => request(`/api/claims/${id}/completeness`, withAuth()),
  submitClaim: (id) =>
    request(`/api/claims/${id}/submit`, withAuth({ method: "POST" })),
  uploadDocument: (id, docType, file) => {
    const fd = new FormData();
    fd.append("doc_type", docType);
    fd.append("file", file);
    return request(
      `/api/claims/${id}/documents`,
      withAuth({ method: "POST", body: fd, isForm: true })
    );
  },
};
