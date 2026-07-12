import { Link } from "react-router-dom";

export default function PolicyShell({ title, updated, children }) {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-200">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <Link to="/" className="text-sm font-semibold text-navy">
            PreAuthIQ
          </Link>
          <Link to="/app/login" className="text-sm text-brand hover:underline">
            Sign in
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-semibold text-navy">{title}</h1>
        {updated && <p className="mt-1 text-sm text-gray-400">Last updated {updated}</p>}
        <div className="prose-policy mt-6 space-y-6 text-sm leading-relaxed text-gray-600">
          {children}
        </div>
        <div className="mt-10 flex gap-4 text-xs text-gray-400">
          <Link to="/privacy" className="hover:text-navy">Privacy Policy</Link>
          <Link to="/cookies" className="hover:text-navy">Cookie Policy</Link>
          <Link to="/" className="hover:text-navy">Home</Link>
        </div>
      </main>
    </div>
  );
}

export function Section({ heading, children }) {
  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold text-navy">{heading}</h2>
      {children}
    </section>
  );
}
