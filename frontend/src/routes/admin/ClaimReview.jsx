import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import RadialGauge from "../../components/RadialGauge";
import { Alert, Button, Card, Modal, Skeleton, Spinner, StatusBadge } from "../../components/ui";
import {
  CLAIM_TYPE_LABEL,
  DOC_TYPE_LABEL,
  VERDICT,
  formatDate,
  formatDateTime,
  money,
} from "../../lib/format";
import { sendDecisionEmail, isEmailConfigured } from "../../lib/email";
import { errorMessage } from "../../lib/http";
import { adminApi, documentObjectUrl } from "./adminApi";

// ---- document preview ----------------------------------------------------
function DocPreview({ doc }) {
  const [obj, setObj] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let revoke;
    setObj(null);
    setErr("");
    if (!doc) return;
    documentObjectUrl(doc.id)
      .then((res) => {
        revoke = res.url;
        setObj(res);
      })
      .catch(() => setErr("Could not load document"));
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [doc]);

  if (!doc) return <div className="p-6 text-sm text-gray-400">Select a document to preview.</div>;
  if (err) return <div className="p-6 text-sm text-red-600">{err}</div>;
  if (!obj) return <div className="flex h-64 items-center justify-center text-brand"><Spinner /></div>;

  if (obj.type.includes("pdf")) {
    return <iframe title={doc.filename} src={obj.url} className="h-[520px] w-full rounded-lg border border-gray-200" />;
  }
  return (
    <div className="flex justify-center">
      <img src={obj.url} alt={doc.filename} className="max-h-[520px] rounded-lg border border-gray-200" />
    </div>
  );
}

// ---- score breakdown -----------------------------------------------------
function ScoreBreakdown({ review }) {
  const bd = review.score_breakdown;
  if (!bd) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>AI confidence {review.ai_score}</span>
        <span>Deterministic {review.deterministic_score}</span>
      </div>
      <div className="text-[11px] text-gray-400">
        final = round(0.5 × AI + 0.5 × deterministic)
      </div>
      <ul className="mt-2 space-y-1.5">
        {bd.components.map((c) => (
          <li key={c.key} className="flex items-start justify-between gap-3 text-sm">
            <span className="flex items-center gap-2">
              <span
                className={`mt-0.5 flex h-4 w-4 items-center justify-center rounded-full text-[10px] ${
                  c.passed ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                }`}
              >
                {c.passed ? "✓" : "✕"}
              </span>
              <span className="text-navy">{c.label}</span>
            </span>
            <span className="whitespace-nowrap text-gray-400">+{c.points}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- agent pipeline ------------------------------------------------------
const AGENT_ORDER = [
  "registration", "completeness", "document_integrity", "coverage", "pre_authorization", "denial",
];

function agentDetail(agent) {
  const o = agent.output || {};
  switch (agent.key) {
    case "registration":
      return o.summary || (o.registered ? "Registered." : "Not registered.");
    case "completeness":
      return o.assessment || (o.complete ? "Documents complete." : "Documents incomplete.");
    case "document_integrity":
      return o.assessment || (o.identity_match ? "Identity matches." : "Identity mismatch.");
    case "coverage":
      return o.assessment || (o.covered ? "Covered." : "Not covered.");
    case "pre_authorization":
      return o.reasoning || "";
    case "denial":
      return o.customer_message || "";
    default:
      return "";
  }
}

function agentChips(agent) {
  const o = agent.output || {};
  const chips = [];
  if (agent.key === "completeness") {
    chips.push(o.complete ? "complete" : "incomplete");
    if (typeof o.confidence === "number") chips.push(`conf ${o.confidence}`);
  }
  if (agent.key === "document_integrity") {
    chips.push(o.identity_match ? "identity match" : "IDENTITY MISMATCH");
    if (o.authenticity_verdict) chips.push(o.authenticity_verdict);
    if (typeof o.risk_score === "number") chips.push(`risk ${o.risk_score}`);
  }
  if (agent.key === "coverage") {
    chips.push(o.covered ? "covered" : "not covered");
    chips.push(o.within_limit ? "within limit" : "over limit");
    (o.exclusions_triggered || []).forEach((e) => chips.push(`excl: ${e}`));
  }
  if (agent.key === "pre_authorization") {
    if (o.verdict) chips.push(o.verdict);
    if (typeof o.confidence === "number") chips.push(`conf ${o.confidence}`);
  }
  return chips;
}

function IntegrityBanner({ integrity }) {
  if (!integrity) return null;
  const det = integrity.deterministic || {};
  const unverifiable = det.unverifiable_documents || [];
  const bad = integrity.blocked || integrity.identity_match === false;
  const ocrUsed = integrity.ocr_used;
  const ocrScore = integrity.ocr_score;

  // Nothing noteworthy: clean, no OCR, no unverifiable docs.
  if (!bad && !unverifiable.length && !ocrUsed) return null;

  const tone = bad
    ? "bg-red-50 border-red-200 text-red-800"
    : unverifiable.length
    ? "bg-amber-50 border-amber-200 text-amber-800"
    : "bg-green-50 border-green-200 text-green-800";

  const title = bad
    ? "Document integrity check failed"
    : unverifiable.length
    ? "Documents partially verified"
    : "Documents verified (incl. OCR)";

  return (
    <div className={`rounded-xl border p-4 ${tone}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M8.5 2.7a1.7 1.7 0 013 0l6 10.6A1.7 1.7 0 0116 16H4a1.7 1.7 0 01-1.5-2.7l6-10.6zM10 7v4m0 3h.01" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
        {title}
        {ocrUsed && ocrScore != null && (
          <span className="rounded-full bg-white/60 px-2 py-0.5 text-[11px] font-medium">
            OCR match score {ocrScore}%
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1 text-sm">
        {integrity.identity_match === false && (
          <p>
            The account holder's name could not be confirmed against the readable
            documents{det.account_name ? ` (account: ${det.account_name})` : ""}. Approval is
            blocked — verify identity manually before deciding.
          </p>
        )}
        {typeof integrity.risk === "number" && bad && <p>Fraud risk score: {integrity.risk}/100.</p>}
        {ocrUsed && (
          <p>
            {det.ocr_mean_confidence != null
              ? `Read ${det.ocr_mean_confidence}% avg OCR confidence; `
              : ""}
            identity match confidence {ocrScore != null ? `${ocrScore}%` : "n/a"}.
          </p>
        )}
        {unverifiable.length > 0 && (
          <p>Could not read (even with OCR): {unverifiable.join(", ")}.</p>
        )}
      </div>
    </div>
  );
}

function AgentPipeline({ agents }) {
  if (!agents?.length) return null;
  const ordered = [...agents].sort(
    (a, b) => (a.sequence || 0) - (b.sequence || 0) ||
      AGENT_ORDER.indexOf(a.key) - AGENT_ORDER.indexOf(b.key)
  );
  return (
    <Card className="p-5">
      <div className="label mb-4">Agent pipeline</div>
      <ol className="space-y-3">
        {ordered.map((a) => (
          <li key={a.key} className="flex gap-3">
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
              {a.sequence}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-navy">{a.name}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    a.status === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                  }`}
                >
                  {a.status}
                </span>
                {a.latency_ms != null && (
                  <span className="text-[10px] text-gray-400">{a.latency_ms} ms</span>
                )}
                {agentChips(a).map((chip, i) => (
                  <span key={i} className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-500">
                    {chip}
                  </span>
                ))}
              </div>
              <p className="mt-1 text-sm text-gray-500">{agentDetail(a)}</p>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

// ---- result modal --------------------------------------------------------
function ResultModal({ open, onClose, review, onAccept, onManual }) {
  if (!review) return null;
  const v = VERDICT[review.verdict] || VERDICT.needs_info;
  return (
    <Modal open={open} onClose={onClose} className="max-w-xl">
      <div className="border-b border-gray-100 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-navy">AI review result</div>
          <span className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ${v.classes}`}>
            {v.label}
          </span>
        </div>
      </div>
      <div className="max-h-[70vh] overflow-y-auto px-6 py-5">
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
          <RadialGauge value={review.final_score} />
          <div className="flex-1">
            <div className="label">Reasoning</div>
            <p className="mt-1 text-sm text-navy">{review.reasoning_summary}</p>
          </div>
        </div>

        <div className="mt-5 rounded-lg bg-gray-50 p-4">
          <div className="label mb-2">Score breakdown</div>
          <ScoreBreakdown review={review} />
        </div>

        {review.flags_json?.length > 0 && (
          <div className="mt-4">
            <div className="label mb-2">Flags</div>
            <ul className="flex flex-wrap gap-2">
              {review.flags_json.map((f, i) => (
                <li key={i} className="rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-700">
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {review.policy_citations?.length > 0 && (
          <div className="mt-4">
            <div className="label mb-2">Policy citations</div>
            <ul className="list-inside list-disc space-y-1 text-sm text-gray-500">
              {review.policy_citations.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="flex justify-end gap-3 border-t border-gray-100 px-6 py-4">
        <Button variant="ghost" onClick={onManual}>
          Decide manually
        </Button>
        <Button onClick={onAccept}>Accept AI recommendation</Button>
      </div>
    </Modal>
  );
}

// ---- main ----------------------------------------------------------------
const VERDICT_TO_ACTION = { approve: "approved", reject: "rejected", needs_info: "requested_info" };
const ACTIONS = [
  { key: "approved", label: "Approve" },
  { key: "rejected", label: "Reject" },
  { key: "requested_info", label: "Request More Info" },
];

export default function ClaimReview() {
  const { id } = useParams();
  const [claim, setClaim] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [error, setError] = useState("");

  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [review, setReview] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);

  const [action, setAction] = useState("");
  const [message, setMessage] = useState("");
  const [agreed, setAgreed] = useState(null);
  const [deciding, setDeciding] = useState(false);
  const [decideError, setDecideError] = useState("");
  const [savedNote, setSavedNote] = useState("");

  const load = async () => {
    try {
      const data = await adminApi.getClaim(id);
      setClaim(data);
      if (!selectedDoc && data.documents.length) setSelectedDoc(data.documents[0]);
      const last = data.ai_reviews[data.ai_reviews.length - 1];
      if (last && !review) setReview(last);
      if (data.customer_message && !message) setMessage(data.customer_message);
    } catch (err) {
      setError(errorMessage(err, "Could not load claim"));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const runReview = async () => {
    setReviewError("");
    setReviewing(true);
    try {
      const res = await adminApi.runAiReview(id);
      setReview(res);
      setModalOpen(true);
      await load();
    } catch (err) {
      setReviewError(errorMessage(err, "AI review failed"));
    } finally {
      setReviewing(false);
    }
  };

  const acceptAi = () => {
    if (!review) return;
    setAction(VERDICT_TO_ACTION[review.verdict]);
    setMessage(review.customer_message_suggestion || review.reasoning_summary || "");
    setAgreed(true);
    setModalOpen(false);
  };

  const decideManually = () => {
    setAgreed(false);
    setModalOpen(false);
  };

  const submitDecision = async () => {
    setDecideError("");
    setSavedNote("");
    if (!action) {
      setDecideError("Choose a decision.");
      return;
    }
    if (!message.trim()) {
      setDecideError("Add a message for the customer.");
      return;
    }
    setDeciding(true);
    try {
      await adminApi.decide(id, {
        action,
        customer_message: message.trim(),
        agreed_with_ai: review ? agreed : null,
      });

      const notifyPayload = { action, customer_message: message.trim() };
      const tasks = [];

      if (isEmailConfigured()) {
        tasks.push(
          sendDecisionEmail({
            toEmail: claim.customer.email,
            toName: claim.customer.full_name,
            claimId: claim.id,
            action,
            message: message.trim(),
            claimType: CLAIM_TYPE_LABEL[claim.claim_type] || claim.claim_type,
          }).then(() => ({ channel: "email", ok: true })),
        );
      }

      tasks.push(
        adminApi
          .notifyCall(id, notifyPayload)
          .then((res) => ({
            channel: "call",
            ok: res.ok !== false,
            skipped: res.skipped,
            reason: res.reason,
          }))
          .catch((err) => ({ channel: "call", ok: false, error: err })),
      );

      const results = await Promise.all(tasks);
      const emailResult = results.find((r) => r.channel === "email");
      const callResult = results.find((r) => r.channel === "call");

      const parts = ["Decision saved."];
      if (emailResult?.ok) parts.push("Email sent.");
      else if (isEmailConfigured() && emailResult && !emailResult.ok) parts.push("Email failed.");

      if (callResult?.ok && !callResult.skipped) parts.push("Phone call initiated.");
      else if (callResult && (callResult.skipped || !callResult.ok)) {
        // Surface the backend/n8n reason instead of a bare "Call failed".
        const msg = callResult.reason || callResult.error?.message || "Call failed";
        parts.push(msg.includes("no phone") ? "No customer phone on file." : `Call failed — ${msg}`);
      }

      setSavedNote(parts.join(" "));

      await load();
    } catch (err) {
      setDecideError(errorMessage(err, "Could not save decision"));
    } finally {
      setDeciding(false);
    }
  };

  if (error) return <Alert>{error}</Alert>;
  if (!claim) return <Skeleton className="h-96" />;

  const plan = claim.plan;
  const rules = plan?.rules_json || {};
  const requiredForType = (rules.required_documents || {})[claim.claim_type] || [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <Link to="/admin" className="text-sm text-gray-400 hover:text-navy">
          ← Back to queue
        </Link>
        <StatusBadge status={claim.status} />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold text-navy">
            Claim #{claim.id} · {CLAIM_TYPE_LABEL[claim.claim_type] || claim.claim_type}
          </h1>
          <p className="mt-0.5 text-sm text-gray-500">
            {claim.customer.full_name} · {plan?.name}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {reviewing && (
            <span className="text-sm text-gray-400">
              Running 5 agents against {plan?.name} rules…
            </span>
          )}
          <Button onClick={runReview} loading={reviewing}>
            {review ? "Re-run AI Review" : "Run AI Review"}
          </Button>
          {review && !modalOpen && (
            <Button variant="ghost" onClick={() => setModalOpen(true)}>
              View AI result
            </Button>
          )}
        </div>
      </div>

      {reviewError && <Alert>{reviewError}</Alert>}

      {review?.integrity && <IntegrityBanner integrity={review.integrity} />}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Left — documents */}
        <div className="space-y-3">
          <Card className="p-4">
            <div className="label mb-3">Documents ({claim.documents.length})</div>
            {claim.documents.length === 0 ? (
              <p className="text-sm text-gray-400">No documents uploaded.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {claim.documents.map((d) => (
                  <button
                    key={d.id}
                    onClick={() => setSelectedDoc(d)}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                      selectedDoc?.id === d.id
                        ? "border-brand bg-brand-soft text-brand"
                        : "border-gray-200 text-gray-500 hover:bg-gray-50"
                    }`}
                  >
                    {DOC_TYPE_LABEL[d.doc_type]}
                  </button>
                ))}
              </div>
            )}
          </Card>
          <Card className="p-4">
            <DocPreview doc={selectedDoc} />
          </Card>
        </div>

        {/* Right — details, profile, rules */}
        <div className="space-y-5">
          <Card className="grid grid-cols-2 gap-y-4 p-5 text-sm">
            <div>
              <div className="label">Amount</div>
              <div className="mt-1 text-navy">{money(claim.amount)}</div>
            </div>
            <div>
              <div className="label">Date of service</div>
              <div className="mt-1 text-navy">{formatDate(claim.date_of_service)}</div>
            </div>
            <div>
              <div className="label">Provider</div>
              <div className="mt-1 text-navy">{claim.provider_name}</div>
            </div>
            <div>
              <div className="label">Submitted</div>
              <div className="mt-1 text-navy">{formatDate(claim.created_at)}</div>
            </div>
            {claim.diagnosis_text && (
              <div className="col-span-2">
                <div className="label">Diagnosis / reason</div>
                <div className="mt-1 text-navy">{claim.diagnosis_text}</div>
              </div>
            )}
          </Card>

          <Card className="p-5 text-sm">
            <div className="label mb-3">Customer</div>
            <div className="grid grid-cols-2 gap-y-3">
              <div>
                <div className="text-xs text-gray-400">Name</div>
                <div className="text-navy">{claim.customer.full_name}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Member ID</div>
                <div className="text-navy">{claim.customer.member_id}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Email</div>
                <div className="text-navy">{claim.customer.email}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">DOB</div>
                <div className="text-navy">{claim.customer.dob}</div>
              </div>
            </div>
          </Card>

          <Card className="p-5 text-sm">
            <div className="label mb-3">Plan rules · {plan?.name}</div>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <div className="text-xs text-gray-400">Annual limit</div>
                  <div className="text-navy">{money(plan?.annual_limit)}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-400">Used</div>
                  <div className="text-navy">{money(claim.financials.used_amount)}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-400">Remaining</div>
                  <div className="text-navy">{money(claim.financials.remaining_limit)}</div>
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Covered categories</div>
                <div className="text-navy">{(rules.covered_categories || []).join(", ") || "—"}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Exclusions</div>
                <div className="text-navy">{(rules.exclusions || []).join(", ") || "—"}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Required docs for this claim type</div>
                <div className="text-navy">
                  {requiredForType.map((d) => DOC_TYPE_LABEL[d]).join(", ") || "—"}
                </div>
              </div>
              {claim.completeness && (
                <div>
                  <div className="text-xs text-gray-400">Completeness</div>
                  <div className={claim.completeness.complete ? "text-green-700" : "text-red-600"}>
                    {claim.completeness.complete
                      ? "All required documents present"
                      : `Missing: ${claim.completeness.missing.map((m) => DOC_TYPE_LABEL[m]).join(", ")}`}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* AI summary card (persisted latest review) */}
      {review && (
        <Card className="p-5">
          <div className="flex items-start gap-5">
            <RadialGauge value={review.final_score} size={104} />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${
                    (VERDICT[review.verdict] || VERDICT.needs_info).classes
                  }`}
                >
                  {(VERDICT[review.verdict] || VERDICT.needs_info).label}
                </span>
                <span className="text-xs text-gray-400">
                  {review.provider} · {review.model}
                </span>
              </div>
              <p className="mt-2 text-sm text-navy">{review.reasoning_summary}</p>
              <div className="mt-3">
                <ScoreBreakdown review={review} />
              </div>
            </div>
          </div>
        </Card>
      )}

      {review?.agents?.length > 0 && <AgentPipeline agents={review.agents} />}

      {/* Decision panel */}
      <Card className="p-5">
        <div className="label mb-3">Decision</div>
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map((a) => (
            <button
              key={a.key}
              onClick={() => setAction(a.key)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                action === a.key
                  ? "border-brand bg-brand text-white"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>

        <div className="mt-4">
          <div className="label mb-1.5">Message to customer</div>
          <textarea
            className="input min-h-[120px]"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Explain the decision in plain language…"
          />
          {review && (
            <p className="mt-1.5 text-xs text-gray-400">
              {agreed === true
                ? "Prefilled from the AI recommendation — edit freely."
                : agreed === false
                ? "Manual decision — not following the AI recommendation."
                : "You can accept the AI recommendation to prefill this."}
            </p>
          )}
        </div>

        {decideError && <div className="mt-3"><Alert>{decideError}</Alert></div>}
        {savedNote && <div className="mt-3"><Alert tone="success">{savedNote}</Alert></div>}

        <div className="mt-4 flex justify-end">
          <Button onClick={submitDecision} loading={deciding}>
            Save decision
          </Button>
        </div>
      </Card>

      {/* History */}
      {claim.admin_actions.length > 0 && (
        <Card className="p-5">
          <div className="label mb-3">Decision history</div>
          <ul className="space-y-2 text-sm">
            {claim.admin_actions.map((a) => (
              <li key={a.id} className="flex items-start justify-between gap-4">
                <div>
                  <span className="font-medium text-navy capitalize">{a.action.replace("_", " ")}</span>
                  <span className="ml-2 text-gray-500">{a.reason_text}</span>
                </div>
                <span className="whitespace-nowrap text-xs text-gray-400">
                  {formatDateTime(a.created_at)}
                  {a.agreed_with_ai != null && (
                    <span className="ml-2">{a.agreed_with_ai ? "· agreed with AI" : "· overrode AI"}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ResultModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        review={review}
        onAccept={acceptAi}
        onManual={decideManually}
      />
    </div>
  );
}
