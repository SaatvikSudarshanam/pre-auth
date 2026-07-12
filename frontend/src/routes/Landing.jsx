import { Link } from "react-router-dom";

import { Button } from "../components/ui";

const AGENTS = [
  { pct: "44%", text: "faster pre-authorization processing", name: "Pre-Authorization Agent" },
  { pct: "41%", text: "faster coverage verification", name: "Coverage Verification Agent" },
  { pct: "45%", text: "faster claims registration", name: "Claims Registration Agent" },
  { pct: "39%", text: "faster completeness assessment", name: "Doc Completeness Agent" },
  { pct: "38%", text: "faster denial letter preparation", name: "Denial Communication Agent" },
];

function BrandMark() {
  return (
    <div className="flex items-center gap-2">
      <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="2" y="2" width="20" height="20" rx="6" fill="#0E9594" />
        <path d="M7 12.5l3 3 7-7" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="text-sm font-semibold text-navy">PreAuthIQ</span>
    </div>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <BrandMark />
          <nav className="flex items-center gap-4 text-sm">
            <Link to="/admin/login" className="text-gray-500 hover:text-navy">
              Admin
            </Link>
            <Link to="/app/login">
              <Button>Sign in</Button>
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4">
        <section className="py-16 sm:py-20">
          <p className="label">Insurance pre-authorization</p>
          <h1 className="mt-3 max-w-2xl text-3xl font-semibold leading-tight text-navy sm:text-4xl">
            Five AI agents layered on your existing claims stack.
          </h1>
          <p className="mt-4 max-w-xl text-base text-gray-500">
            End-to-end pre-authorization with a human in the loop — registration,
            coverage, completeness, adjudication, and customer communication.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link to="/app/login">
              <Button className="px-5">Get started</Button>
            </Link>
            <Link to="/app/login">
              <Button variant="ghost" className="px-5">
                Member sign in
              </Button>
            </Link>
          </div>
        </section>

        {/* 5 agents — the measurable turnaround gains */}
        <section className="pb-8">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {AGENTS.map((a) => (
              <div
                key={a.name}
                className="flex flex-col rounded-xl border border-gray-200 bg-white shadow-card"
              >
                <div className="h-1.5 rounded-t-xl bg-brand" />
                <div className="flex flex-1 flex-col p-5">
                  <div className="text-3xl font-semibold text-navy">{a.pct}</div>
                  <div className="mt-2 text-sm text-gray-500">{a.text}</div>
                  <div className="mt-6 text-[11px] font-semibold uppercase tracking-wide text-brand">
                    {a.name}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="pb-16">
          <div className="rounded-xl bg-navy px-6 py-6 text-sm leading-relaxed text-white/90 sm:px-8">
            A compliance deadline, provider abrasion, and measurable turnaround gains
            all point the same way: AI agents layered on your existing claims stack,
            not a rip-and-replace.
          </div>
        </section>
      </main>

      <footer className="border-t border-gray-200">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-gray-400 sm:flex-row">
          <span>© 2026 PreAuthIQ — demo</span>
          <nav className="flex items-center gap-4">
            <Link to="/privacy" className="hover:text-navy">
              Privacy Policy
            </Link>
            <Link to="/cookies" className="hover:text-navy">
              Cookie Policy
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
