import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Alert, Button, Card, Field, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { setCustomerToken } from "../../lib/auth";
import { errorMessage } from "../../lib/http";

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.02-3.7H.96v2.34A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.98 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.02-2.34z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.94l3.02 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

export default function Login() {
  const nav = useNavigate();
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res =
        mode === "signin"
          ? await api.login(email, password)
          : await api.signup(email, password);
      setCustomerToken(res.access_token);
      nav(res.profile_complete ? "/app" : "/app/profile", { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Could not sign in"));
    } finally {
      setLoading(false);
    }
  };

  const google = async () => {
    setError("");
    setGoogleLoading(true);
    try {
      const { url } = await api.googleLoginUrl();
      window.location.href = url; // full-page redirect to Google consent
    } catch (err) {
      setError(errorMessage(err, "Google sign-in is unavailable"));
      setGoogleLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <Link to="/" className="text-lg font-semibold text-navy">
            PreAuthIQ
          </Link>
          <p className="mt-1 text-sm text-gray-400">Member sign in</p>
        </div>
        <Card className="p-6">
          <button
            onClick={google}
            disabled={googleLoading}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-navy transition hover:bg-gray-50 disabled:opacity-50"
          >
            {googleLoading ? <Spinner className="h-4 w-4" /> : <GoogleIcon />}
            Continue with Google
          </button>

          <div className="my-5 flex items-center gap-3 text-xs text-gray-400">
            <span className="h-px flex-1 bg-gray-200" />
            or
            <span className="h-px flex-1 bg-gray-200" />
          </div>

          <div className="mb-5 flex rounded-lg bg-gray-100 p-1 text-sm">
            {["signin", "signup"].map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m);
                  setError("");
                }}
                className={`flex-1 rounded-md py-1.5 font-medium transition ${
                  mode === m ? "bg-white text-navy shadow-card" : "text-gray-500"
                }`}
              >
                {m === "signin" ? "Sign in" : "Sign up"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            <Field label="Email">
              <input
                className="input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field>
            <Field label="Password" hint={mode === "signup" ? "At least 6 characters" : undefined}>
              <input
                className="input"
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
            </Field>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" loading={loading} className="w-full">
              {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </Card>

        <p className="mt-4 text-center text-xs text-gray-400">
          Demo customers: alice@example.com / ravi@example.com — password{" "}
          <span className="font-medium">Passw0rd!</span>
        </p>
        <p className="mt-2 text-center text-xs text-gray-400">
          <Link to="/admin/login" className="text-brand hover:underline">
            Admin sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
