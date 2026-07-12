import { STATUS } from "../lib/format";

export function Button({
  variant = "primary",
  loading = false,
  className = "",
  children,
  disabled,
  ...props
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-brand text-white hover:bg-brand-hover",
    ghost: "border border-gray-200 bg-white text-navy hover:bg-gray-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
    subtle: "bg-brand-soft text-brand hover:bg-brand/20",
  };
  return (
    <button
      className={`${base} ${variants[variant]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Card({ className = "", children, ...props }) {
  return (
    <div
      className={`rounded-xl border border-gray-200 bg-white shadow-card transition hover:shadow-hover ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.draft;
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${s.classes}`}>
      {s.label}
    </span>
  );
}

export function Spinner({ className = "h-5 w-5" }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z"
      />
    </svg>
  );
}

export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-md bg-gray-100 ${className}`} />;
}

export function Field({ label, children, hint, error }) {
  return (
    <label className="block space-y-1.5">
      <span className="label block">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-gray-400">{hint}</span>}
      {error && <span className="block text-xs text-red-600">{error}</span>}
    </label>
  );
}

export function EmptyState({ line, action }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <p className="text-sm text-gray-500">{line}</p>
      {action}
    </div>
  );
}

export function Modal({ open, onClose, children, className = "" }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-navy/30 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        className={`w-full max-w-lg rounded-xl border border-gray-200 bg-white shadow-hover ${className}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export function Alert({ tone = "error", children }) {
  const tones = {
    error: "bg-red-50 text-red-700 border-red-200",
    info: "bg-blue-50 text-blue-700 border-blue-200",
    success: "bg-green-50 text-green-700 border-green-200",
  };
  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${tones[tone]}`}>{children}</div>
  );
}
