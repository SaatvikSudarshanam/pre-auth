import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, Button, Card, Field } from "../../components/ui";
import { setAdminToken } from "../../lib/auth";
import { errorMessage } from "../../lib/http";
import { adminApi } from "./adminApi";

export default function AdminLogin() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await adminApi.login(username, password);
      setAdminToken(res.access_token);
      nav("/admin", { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Invalid credentials"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-lg font-semibold text-navy">Reviewer Console</div>
          <p className="mt-1 text-sm text-gray-400">Admin access</p>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <Field label="Username">
              <input
                className="input"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
              />
            </Field>
            <Field label="Password">
              <input
                className="input"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </Field>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" loading={loading} className="w-full">
              Sign in
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-gray-400">
          Demo credentials in <span className="font-medium">.env</span> — replace before production.
        </p>
      </div>
    </div>
  );
}
