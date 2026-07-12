import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Alert, Button, Card, Skeleton, StatusBadge } from "../../components/ui";
import { api } from "../../lib/api";
import {
  CLAIM_TYPE_LABEL,
  DOC_TYPE_LABEL,
  formatDate,
  formatDateTime,
  money,
} from "../../lib/format";
import { errorMessage } from "../../lib/http";

const DOC_TYPES = ["prescription", "itemized_bill", "discharge_summary", "lab_report", "id_proof", "other"];

function Timeline({ events }) {
  if (!events?.length) return <p className="text-sm text-gray-400">No history yet.</p>;
  return (
    <ol className="space-y-4">
      {events.map((e, i) => (
        <li key={i} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className="mt-1 h-2.5 w-2.5 rounded-full bg-brand" />
            {i < events.length - 1 && <span className="mt-1 w-px flex-1 bg-gray-200" />}
          </div>
          <div className="pb-1">
            <div className="text-sm font-medium text-navy">{e.note || e.status}</div>
            <div className="text-xs text-gray-400">{formatDateTime(e.created_at)}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function MoreInfoUpload({ claimId, onDone }) {
  const inputRef = useRef(null);
  const [docType, setDocType] = useState("itemized_bill");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr("");
    setBusy(true);
    try {
      await api.uploadDocument(claimId, docType, file);
      await onDone();
    } catch (ex) {
      setErr(errorMessage(ex, "Upload failed"));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <Card className="space-y-3 p-5">
      <div className="text-sm font-medium text-navy">Add a document</div>
      <p className="text-xs text-gray-400">
        Uploading a document returns your claim to review.
      </p>
      <div className="flex items-center gap-3">
        <select className="input max-w-[220px]" value={docType} onChange={(e) => setDocType(e.target.value)}>
          {DOC_TYPES.map((d) => (
            <option key={d} value={d}>
              {DOC_TYPE_LABEL[d]}
            </option>
          ))}
        </select>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          className="hidden"
          onChange={pick}
        />
        <Button variant="subtle" loading={busy} onClick={() => inputRef.current?.click()}>
          Choose file
        </Button>
      </div>
      {err && <Alert>{err}</Alert>}
    </Card>
  );
}

export default function ClaimDetail() {
  const { id } = useParams();
  const [claim, setClaim] = useState(null);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setClaim(await api.getClaim(id));
    } catch (err) {
      setError(errorMessage(err, "Could not load claim"));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error) return <Alert>{error}</Alert>;
  if (!claim) return <Skeleton className="h-64" />;

  const decided = ["approved", "rejected", "more_info_needed"].includes(claim.status);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/app" className="text-sm text-gray-400 hover:text-navy">
        ← Back to dashboard
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-navy">
            {CLAIM_TYPE_LABEL[claim.claim_type] || claim.claim_type}
          </h1>
          <p className="mt-1 text-sm text-gray-500">{claim.provider_name}</p>
        </div>
        <StatusBadge status={claim.status} />
      </div>

      <Card className="grid grid-cols-2 gap-y-4 p-6 text-sm sm:grid-cols-3">
        <div>
          <div className="label">Amount</div>
          <div className="mt-1 text-navy">{money(claim.amount)}</div>
        </div>
        <div>
          <div className="label">Date of service</div>
          <div className="mt-1 text-navy">{formatDate(claim.date_of_service)}</div>
        </div>
        <div>
          <div className="label">Submitted</div>
          <div className="mt-1 text-navy">{formatDate(claim.created_at)}</div>
        </div>
        {claim.diagnosis_text && (
          <div className="col-span-2 sm:col-span-3">
            <div className="label">Diagnosis / reason</div>
            <div className="mt-1 text-navy">{claim.diagnosis_text}</div>
          </div>
        )}
      </Card>

      {decided && claim.customer_message && (
        <Alert
          tone={
            claim.status === "approved"
              ? "success"
              : claim.status === "rejected"
              ? "error"
              : "info"
          }
        >
          {claim.customer_message}
        </Alert>
      )}

      {claim.status === "more_info_needed" && (
        <MoreInfoUpload claimId={claim.id} onDone={load} />
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <div className="label mb-4">Status timeline</div>
          <Timeline events={claim.events} />
        </Card>
        <Card className="p-6">
          <div className="label mb-4">Documents</div>
          {claim.documents.length === 0 ? (
            <p className="text-sm text-gray-400">No documents.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {claim.documents.map((d) => (
                <li key={d.id} className="flex items-center justify-between">
                  <span className="text-navy">{DOC_TYPE_LABEL[d.doc_type]}</span>
                  <span className="text-xs text-gray-400">{d.filename}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
