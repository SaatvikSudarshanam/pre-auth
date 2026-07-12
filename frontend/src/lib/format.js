const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export const money = (n) => (n == null ? "—" : inr.format(n));

export const formatDate = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d)) return v;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

export const formatDateTime = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d)) return v;
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const STATUS = {
  submitted: { label: "Submitted", classes: "bg-slate-100 text-slate-600" },
  under_review: { label: "Under Review", classes: "bg-amber-50 text-amber-700" },
  more_info_needed: { label: "More Info Needed", classes: "bg-blue-50 text-blue-700" },
  approved: { label: "Approved", classes: "bg-green-50 text-green-700" },
  rejected: { label: "Rejected", classes: "bg-red-50 text-red-700" },
  draft: { label: "Draft", classes: "bg-gray-100 text-gray-500" },
};

export const CLAIM_TYPE_LABEL = {
  hospitalization: "Hospitalization",
  procedure: "Procedure",
  pharmacy: "Pharmacy",
  preauth_request: "Pre-auth Request",
};

export const DOC_TYPE_LABEL = {
  prescription: "Prescription",
  itemized_bill: "Itemized Bill",
  discharge_summary: "Discharge Summary",
  lab_report: "Lab Report",
  id_proof: "ID Proof",
  other: "Other",
};

export const VERDICT = {
  approve: { label: "Approve", classes: "bg-green-50 text-green-700 ring-green-200" },
  reject: { label: "Reject", classes: "bg-red-50 text-red-700 ring-red-200" },
  needs_info: { label: "Needs Info", classes: "bg-blue-50 text-blue-700 ring-blue-200" },
};
