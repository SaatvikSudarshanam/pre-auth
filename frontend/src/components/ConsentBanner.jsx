import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { Button } from "./ui";

const KEY = "preauthiq_consent";
const ANON = "preauthiq_anon_id";

function anonId() {
  let id = localStorage.getItem(ANON);
  if (!id) {
    id = (crypto?.randomUUID && crypto.randomUUID()) || `anon-${Date.now()}`;
    localStorage.setItem(ANON, id);
  }
  return id;
}

export default function ConsentBanner() {
  const [show, setShow] = useState(false);
  const [version, setVersion] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    api
      .getPolicies()
      .then((p) => {
        if (!mounted) return;
        setVersion(p.cookie_version);
        let stored = null;
        try {
          stored = JSON.parse(localStorage.getItem(KEY) || "null");
        } catch {
          stored = null;
        }
        // Show if never consented, or the policy version changed.
        if (!stored || stored.version !== p.cookie_version) setShow(true);
      })
      .catch(() => {
        // If policies can't load, still offer the choice with an unknown version.
        if (!localStorage.getItem(KEY)) setShow(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const choose = async (analytics) => {
    setSaving(true);
    const categories = { necessary: true, analytics };
    try {
      await api.recordConsent({
        policy: "cookie",
        version: version || undefined,
        accepted: true,
        categories,
        anon_id: anonId(),
      });
    } catch {
      // Non-blocking: still remember the choice locally.
    } finally {
      localStorage.setItem(
        KEY,
        JSON.stringify({ version: version || "unknown", analytics, ts: Date.now() })
      );
      setShow(false);
      setSaving(false);
    }
  };

  if (!show) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-[60] p-3 sm:p-4">
      <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-hover sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-gray-600">
          We use strictly necessary cookies to keep you signed in. Optional analytics
          are off by default.{" "}
          <Link to="/cookies" className="text-brand hover:underline">
            Cookie Policy
          </Link>
        </p>
        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" loading={saving} onClick={() => choose(false)}>
            Necessary only
          </Button>
          <Button loading={saving} onClick={() => choose(true)}>
            Accept all
          </Button>
        </div>
      </div>
    </div>
  );
}
