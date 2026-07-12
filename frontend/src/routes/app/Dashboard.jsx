import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import { Button, Card, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { api } from "../../lib/api";
import { CLAIM_TYPE_LABEL, formatDate, money } from "../../lib/format";

function PlanSummary({ me }) {
  const plan = me?.plan;
  const used = me?.used_amount || 0;
  const limit = plan?.annual_limit || 0;
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <Card className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="label">Your plan</div>
          <div className="mt-1 text-lg font-semibold text-navy">{plan?.name}</div>
        </div>
        <div className="text-right">
          <div className="label">Member ID</div>
          <div className="mt-1 text-sm font-medium text-navy">{me?.member_id}</div>
        </div>
      </div>
      <div className="mt-5">
        <div className="flex justify-between text-xs text-gray-500">
          <span>Used {money(used)}</span>
          <span>Limit {money(limit)}</span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-gray-100">
          <div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-1.5 text-xs text-gray-400">
          {money(me?.remaining_limit ?? limit)} remaining this year
        </div>
      </div>
    </Card>
  );
}

function ClaimCard({ claim }) {
  return (
    <Link to={`/app/claims/${claim.id}`}>
      <Card className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-sm font-semibold text-navy">
              {CLAIM_TYPE_LABEL[claim.claim_type] || claim.claim_type}
            </div>
            <div className="mt-0.5 text-sm text-gray-500">{claim.provider_name}</div>
          </div>
          <StatusBadge status={claim.status} />
        </div>
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-gray-400">{formatDate(claim.date_of_service)}</span>
          <span className="font-medium text-navy">{money(claim.amount)}</span>
        </div>
      </Card>
    </Link>
  );
}

export default function Dashboard() {
  const { me } = useOutletContext();
  const [claims, setClaims] = useState(null);

  useEffect(() => {
    api.listClaims().then(setClaims).catch(() => setClaims([]));
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-navy">Dashboard</h1>
        <Link to="/app/new">
          <Button>New claim</Button>
        </Link>
      </div>

      <PlanSummary me={me} />

      <div>
        <div className="label mb-3">Your claims</div>
        {claims === null ? (
          <div className="grid gap-4 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        ) : claims.length === 0 ? (
          <Card>
            <EmptyState
              line="You have no claims yet."
              action={
                <Link to="/app/new">
                  <Button>Submit your first claim</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {claims.map((c) => (
              <ClaimCard key={c.id} claim={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
