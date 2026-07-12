import { useEffect, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";

import { Alert, Button, Card, Field, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { money } from "../../lib/format";
import { errorMessage } from "../../lib/http";

export default function CompleteProfile() {
  const { reloadMe } = useOutletContext();
  const nav = useNavigate();
  const [plans, setPlans] = useState(null);
  const [fullName, setFullName] = useState("");
  const [dob, setDob] = useState("");
  const [planId, setPlanId] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .listPlans()
      .then((p) => {
        setPlans(p);
        if (p.length) setPlanId(p[0].id);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api.completeProfile({ full_name: fullName, dob, plan_id: planId });
      await reloadMe();
      nav("/app", { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Could not save profile"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold text-navy">Complete your profile</h1>
      <p className="mt-1 text-sm text-gray-500">
        A few details and your plan choice. Your member ID is generated on save.
      </p>

      <form onSubmit={submit} className="mt-6 space-y-6">
        <Card className="space-y-4 p-6">
          <Field label="Full name">
            <input
              className="input"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name"
            />
          </Field>
          <Field label="Date of birth">
            <input
              className="input"
              type="date"
              required
              value={dob}
              onChange={(e) => setDob(e.target.value)}
            />
          </Field>
        </Card>

        <div>
          <div className="label mb-2">Choose a plan</div>
          {!plans ? (
            <Spinner className="h-5 w-5 text-brand" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              {plans.map((p) => (
                <button
                  type="button"
                  key={p.id}
                  onClick={() => setPlanId(p.id)}
                  className={`rounded-xl border p-4 text-left transition ${
                    planId === p.id
                      ? "border-brand ring-2 ring-brand/20"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="text-sm font-semibold text-navy">{p.name}</div>
                  <div className="mt-2 space-y-1 text-xs text-gray-500">
                    <div>Limit {money(p.annual_limit)}</div>
                    <div>Deductible {money(p.deductible)}</div>
                    <div>Co-pay {p.copay_percent}%</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {error && <Alert>{error}</Alert>}
        <Button type="submit" loading={saving}>
          Save and continue
        </Button>
      </form>
    </div>
  );
}
