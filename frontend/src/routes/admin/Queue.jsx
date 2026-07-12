import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card, Skeleton, StatusBadge } from "../../components/ui";
import { CLAIM_TYPE_LABEL, formatDate, money } from "../../lib/format";
import { adminApi } from "./adminApi";

const FILTERS = [
  { key: "", label: "All" },
  { key: "submitted", label: "Submitted" },
  { key: "under_review", label: "Under Review" },
  { key: "more_info_needed", label: "More Info" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

function Stat({ label, value }) {
  return (
    <Card className="px-5 py-4">
      <div className="label">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-navy">{value}</div>
    </Card>
  );
}

export default function Queue() {
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState(null);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    adminApi.stats().then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(() => {
    setRows(null);
    adminApi.listClaims(status).then(setRows).catch(() => setRows([]));
  }, [status]);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-navy">Claims queue</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Pending" value={stats ? stats.pending : "—"} />
        <Stat label="Decided today" value={stats ? stats.decided_today : "—"} />
        <Stat
          label="AI–admin agreement"
          value={stats && stats.agreement_rate != null ? `${stats.agreement_rate}%` : "—"}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              status === f.key
                ? "bg-brand text-white"
                : "border border-gray-200 bg-white text-gray-500 hover:bg-gray-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-400">
              <tr>
                <th className="px-4 py-3 font-medium">ID</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Plan</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Docs</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows === null ? (
                [0, 1, 2].map((i) => (
                  <tr key={i}>
                    <td className="px-4 py-3" colSpan={8}>
                      <Skeleton className="h-5" />
                    </td>
                  </tr>
                ))
              ) : rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-10 text-center text-gray-400" colSpan={8}>
                    No claims in this view.
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => nav(`/admin/claims/${r.id}`)}
                    className="cursor-pointer hover:bg-gray-50"
                  >
                    <td className="px-4 py-3 font-medium text-navy">#{r.id}</td>
                    <td className="px-4 py-3">
                      <div className="text-navy">{r.customer}</div>
                      <div className="text-xs text-gray-400">{r.customer_email}</div>
                    </td>
                    <td className="px-4 py-3 text-gray-500">{r.plan}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {CLAIM_TYPE_LABEL[r.claim_type] || r.claim_type}
                    </td>
                    <td className="px-4 py-3 text-navy">{money(r.amount)}</td>
                    <td className="px-4 py-3 text-gray-500">{formatDate(r.date_of_service)}</td>
                    <td className="px-4 py-3 text-gray-500">{r.docs_count}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
