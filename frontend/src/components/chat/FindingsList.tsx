import type { AgentFinding, AggregatedOutput } from "../../types/api";

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  warning: 2,
  medium: 3,
  low: 4,
  info: 5,
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ffb4ab",
  high: "#ff7b72",
  warning: "#e7c427",
  medium: "#ffb44d",
  low: "#c2c7d0",
  info: "#849495",
};

function getSeverityColor(severity: string): string {
  return SEVERITY_COLORS[severity.toLowerCase()] ?? SEVERITY_COLORS.info;
}

interface FindingsListProps {
  findings: AgentFinding[];
  parseStatus?: AggregatedOutput["parse_status"];
}

export default function FindingsList({ findings, parseStatus }: FindingsListProps) {
  if (findings.length === 0 && !parseStatus) return null;

  // Sort by severity: critical > high > warning > medium > low > info
  const sorted = [...findings].sort((a, b) => {
    const orderA = SEVERITY_ORDER[a.severity.toLowerCase()] ?? 5;
    const orderB = SEVERITY_ORDER[b.severity.toLowerCase()] ?? 5;
    return orderA - orderB;
  });

  return (
    <div className="space-y-3">
      {/* Surface parse_status when not "ok" — §5.2 */}
      {parseStatus && parseStatus !== "ok" && (
        <div className="flex items-center gap-2 px-3 py-2 bg-surface-container border border-outline-variant rounded text-sm text-on-surface-variant">
          <span className="material-symbols-outlined text-[16px] text-tertiary-fixed-dim">warning</span>
          <span>
            Result parsed with status: <code className="text-on-surface font-code-sm">{parseStatus}</code>
          </span>
        </div>
      )}

      {findings.length > 0 && (
        <>
          <h3 className="font-label-caps text-label-caps text-on-surface-variant opacity-70">
            Findings ({findings.length})
          </h3>
          {sorted.map((finding, i) => {
            const sev = finding.severity.toLowerCase();
            const color = getSeverityColor(sev);
            return (
              <div
                key={i}
                className="border-l-4 bg-surface-container p-4 rounded-r border-t border-b border-r border-outline-variant"
                style={{ borderLeftColor: color }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="px-2 py-0.5 rounded-full font-code-sm text-code-sm"
                    style={{ backgroundColor: `${color}20`, color }}
                  >
                    {sev}
                  </span>
                  <span className="font-body-sm text-on-surface font-semibold">{finding.title}</span>
                </div>
                <p className="font-body-sm text-on-surface-variant mb-2">{finding.description}</p>
                {finding.evidence.length > 0 && (
                  <div className="bg-surface-container-lowest p-3 rounded border border-outline-variant font-code-sm text-code-sm text-[#c9d1d9] overflow-x-auto mb-2">
                    {finding.evidence.map((e, j) => (
                      <div key={j}>{e}</div>
                    ))}
                  </div>
                )}
                {finding.recommendation && (
                  <p className="font-body-sm text-on-surface-variant text-sm">
                    <span className="text-primary-fixed-dim font-semibold">Recommendation:</span>{" "}
                    {finding.recommendation}
                  </p>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
