import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Alert, Button, Card, Field, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { CLAIM_TYPE_LABEL, DOC_TYPE_LABEL, money } from "../../lib/format";
import { errorMessage } from "../../lib/http";

const CLAIM_TYPES = ["hospitalization", "procedure", "pharmacy", "preauth_request"];
const STEPS = ["Claim details", "Documents", "Review & submit"];

function Stepper({ step }) {
  return (
    <div className="flex items-center gap-3">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const active = n === step;
        const done = n < step;
        return (
          <div key={label} className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                  done
                    ? "bg-brand text-white"
                    : active
                    ? "bg-brand-soft text-brand ring-1 ring-brand"
                    : "bg-gray-100 text-gray-400"
                }`}
              >
                {done ? "✓" : n}
              </span>
              <span className={`text-sm ${active ? "font-medium text-navy" : "text-gray-400"}`}>
                {label}
              </span>
            </div>
            {n < STEPS.length && <div className="h-px w-6 bg-gray-200" />}
          </div>
        );
      })}
    </div>
  );
}

function DocRow({ docType, attached, onUpload }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    setBusy(true);
    try {
      await onUpload(docType, file);
    } catch (ex) {
      setErr(errorMessage(ex, "Upload failed"));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3">
      <div className="flex items-center gap-3">
        <span
          className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
            attached ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"
          }`}
        >
          {attached ? "✓" : ""}
        </span>
        <div>
          <div className="text-sm font-medium text-navy">{DOC_TYPE_LABEL[docType]}</div>
          {attached ? (
            <div className="text-xs text-green-700">Attached — {attached.filename}</div>
          ) : (
            <div className="text-xs text-gray-400">Required</div>
          )}
          {err && <div className="text-xs text-red-600">{err}</div>}
        </div>
      </div>
      <div>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          className="hidden"
          onChange={pick}
        />
        <Button
          type="button"
          variant={attached ? "ghost" : "subtle"}
          loading={busy}
          onClick={() => inputRef.current?.click()}
        >
          {attached ? "Replace" : "Upload"}
        </Button>
      </div>
    </div>
  );
}

export default function NewClaim() {
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    claim_type: "hospitalization",
    provider_name: "",
    diagnosis_text: "",
    date_of_service: "",
    amount: "",
  });
  const [claim, setClaim] = useState(null); // draft claim after step 1

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const createDraft = async () => {
    setError("");
    setBusy(true);
    try {
      const payload = { ...form, amount: parseFloat(form.amount || "0") };
      const res = await api.createClaim(payload);
      setClaim(res);
      setStep(2);
    } catch (err) {
      setError(errorMessage(err, "Could not create claim"));
    } finally {
      setBusy(false);
    }
  };

  const onUpload = async (docType, file) => {
    const updated = await api.uploadDocument(claim.id, docType, file);
    setClaim(updated);
  };

  const submit = async () => {
    setError("");
    setBusy(true);
    try {
      await api.submitClaim(claim.id);
      nav(`/app/claims/${claim.id}`, { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Could not submit claim"));
    } finally {
      setBusy(false);
    }
  };

  const attachedFor = (docType) =>
    claim?.documents?.find((d) => d.doc_type === docType) || null;
  const missing = claim?.missing_documents || [];

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold text-navy">New claim</h1>
      <div className="mt-5">
        <Stepper step={step} />
      </div>

      {error && (
        <div className="mt-5">
          <Alert>{error}</Alert>
        </div>
      )}

      {/* Step 1 — details */}
      {step === 1 && (
        <Card className="mt-6 space-y-4 p-6">
          <Field label="Claim type">
            <select className="input" value={form.claim_type} onChange={set("claim_type")}>
              {CLAIM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {CLAIM_TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Provider">
            <input
              className="input"
              value={form.provider_name}
              onChange={set("provider_name")}
              placeholder="Hospital or clinic name"
            />
          </Field>
          <Field label="Diagnosis / reason">
            <textarea
              className="input min-h-[80px]"
              value={form.diagnosis_text}
              onChange={set("diagnosis_text")}
              placeholder="Short description"
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Date of service">
              <input
                className="input"
                type="date"
                value={form.date_of_service}
                onChange={set("date_of_service")}
              />
            </Field>
            <Field label="Amount">
              <input
                className="input"
                type="number"
                min="0"
                value={form.amount}
                onChange={set("amount")}
                placeholder="0"
              />
            </Field>
          </div>
          <div className="flex justify-end pt-2">
            <Button
              onClick={createDraft}
              loading={busy}
              disabled={!form.provider_name || !form.date_of_service || !form.amount}
            >
              Next
            </Button>
          </div>
        </Card>
      )}

      {/* Step 2 — documents */}
      {step === 2 && claim && (
        <div className="mt-6 space-y-4">
          <Card className="space-y-3 p-6">
            <div>
              <div className="text-sm font-medium text-navy">Required documents</div>
              <p className="text-xs text-gray-400">
                All required documents must be attached before you can submit.
              </p>
            </div>
            {claim.required_documents.length === 0 ? (
              <p className="text-sm text-gray-500">No documents required for this claim type.</p>
            ) : (
              <div className="space-y-2">
                {claim.required_documents.map((dt) => (
                  <DocRow key={dt} docType={dt} attached={attachedFor(dt)} onUpload={onUpload} />
                ))}
              </div>
            )}
            {missing.length > 0 && (
              <Alert tone="info">
                Still needed: {missing.map((m) => DOC_TYPE_LABEL[m]).join(", ")}
              </Alert>
            )}
          </Card>
          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={() => setStep(3)} disabled={missing.length > 0}>
              Continue
            </Button>
          </div>
        </div>
      )}

      {/* Step 3 — review */}
      {step === 3 && claim && (
        <div className="mt-6 space-y-4">
          <Card className="p-6">
            <div className="grid grid-cols-2 gap-y-4 text-sm">
              <div>
                <div className="label">Type</div>
                <div className="mt-1 text-navy">{CLAIM_TYPE_LABEL[form.claim_type]}</div>
              </div>
              <div>
                <div className="label">Amount</div>
                <div className="mt-1 text-navy">{money(parseFloat(form.amount || "0"))}</div>
              </div>
              <div>
                <div className="label">Provider</div>
                <div className="mt-1 text-navy">{form.provider_name}</div>
              </div>
              <div>
                <div className="label">Date of service</div>
                <div className="mt-1 text-navy">{form.date_of_service}</div>
              </div>
              <div className="col-span-2">
                <div className="label">Documents</div>
                <div className="mt-1 text-navy">
                  {claim.documents.map((d) => DOC_TYPE_LABEL[d.doc_type]).join(", ")}
                </div>
              </div>
            </div>
          </Card>
          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button onClick={submit} loading={busy}>
              Submit claim
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
