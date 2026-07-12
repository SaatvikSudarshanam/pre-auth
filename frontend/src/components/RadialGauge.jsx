// Radial gauge for the final score (0-100). Color bands: >=75 green, >=50 amber,
// else red.
export default function RadialGauge({ value = 0, size = 128, label = "Final score" }) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const stroke = 10;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c - (v / 100) * c;
  const color = v >= 75 ? "#16a34a" : v >= 50 ? "#d97706" : "#dc2626";

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#eef1f4" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-semibold text-navy">{v}</span>
        <span className="label mt-1">{label}</span>
      </div>
    </div>
  );
}
