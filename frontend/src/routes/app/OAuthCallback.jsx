import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Alert, Spinner } from "../../components/ui";
import { setCustomerToken } from "../../lib/auth";

// Backend redirects here with the token in the URL fragment:
//   /app/oauth#token=<jwt>&complete=<0|1>   or   /app/oauth#error=<code>
export default function OAuthCallback() {
  const nav = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const err = hash.get("error");
    const token = hash.get("token");
    if (err) {
      setError(`Google sign-in failed (${err}).`);
      return;
    }
    if (token) {
      setCustomerToken(token);
      // Clear the token from the address bar before navigating on.
      window.history.replaceState(null, "", "/app/oauth");
      nav(hash.get("complete") === "1" ? "/app" : "/app/profile", { replace: true });
    } else {
      setError("No sign-in token was returned.");
    }
  }, [nav]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-4 text-center">
          <Alert>{error}</Alert>
          <Link to="/app/login" className="text-sm text-brand hover:underline">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center text-brand">
      <Spinner className="h-6 w-6" />
    </div>
  );
}
