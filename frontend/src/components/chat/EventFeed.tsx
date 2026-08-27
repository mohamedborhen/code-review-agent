import { useState, useRef, useEffect } from "react";
import type { ReviewToolCallItem } from "../../types/api";
import { getToolMeta, getCategoryStyle } from "./toolLabels";

const AGENT_COLORS: Record<string, string> = {
  compliance: "#e7c427",
  security: "#ffb4ab",
  performance: "#ffb44d",
  regression: "#c2c7d0",
  fix_suggestion: "#63f7ff",
  context_agent: "#849495",
  aggregator: "#00f5ff",
};

const AGENT_LABELS: Record<string, string> = {
  compliance: "Compliance",
  security: "Security",
  performance: "Performance",
  regression: "Regression",
  fix_suggestion: "Fix Suggestion",
  context_agent: "Context",
  aggregator: "Summary",
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface EventFeedProps {
  toolCalls: ReviewToolCallItem[];
  isRunning: boolean;
}

export default function EventFeed({ toolCalls, isRunning }: EventFeedProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-collapse when >6 calls to keep feed compact
  useEffect(() => {
    if (toolCalls.length > 6 && !collapsed) {
      setCollapsed(true);
    }
  }, [toolCalls.length]);

  // Auto-scroll the inner list to bottom on new items
  useEffect(() => {
    if (!collapsed && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [toolCalls.length, collapsed]);

  if (toolCalls.length === 0 && !isRunning) return null;

  const sorted = [...toolCalls].sort((a, b) =>
    (a.created_at ?? "").localeCompare(b.created_at ?? ""),
  );

  // Group consecutive calls by agent
  const groups: { agent: string; items: ReviewToolCallItem[] }[] = [];
  for (const tc of sorted) {
    const last = groups[groups.length - 1];
    if (last && last.agent === tc.agent_name) {
      last.items.push(tc);
    } else {
      groups.push({ agent: tc.agent_name, items: [tc] });
    }
  }

  return (
    <div className="border border-outline-variant/40 rounded-xl bg-surface-container-low/50 overflow-hidden">
      {/* Header — collapsible toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-surface-container-high/50 transition-colors"
      >
        <span className="material-symbols-outlined text-[18px] text-primary-container">
          smart_toy
        </span>
        <span className="font-label-caps text-label-caps text-on-surface-variant">
          Agent Activity
        </span>
        <span className="font-code-xs text-on-surface-variant/50">
          {sorted.length} call{sorted.length !== 1 ? "s" : ""}
        </span>
        {sorted.some((tc) => tc.tool_status === "error") && (
          <span className="text-error text-[11px] font-medium">
            {sorted.filter((tc) => tc.tool_status === "error").length} failed
          </span>
        )}
        <span className="material-symbols-outlined text-[16px] text-on-surface-variant/40 ml-auto">
          {collapsed ? "expand_more" : "expand_less"}
        </span>
      </button>

      {/* Collapsible body */}
      {!collapsed && (
        <div
          ref={scrollRef}
          className="max-h-[40vh] overflow-y-auto border-t border-outline-variant/20"
        >
          <div className="p-3 space-y-2">
            {groups.map((group) => {
              const agentColor = AGENT_COLORS[group.agent] ?? "#849495";
              const agentLabel = AGENT_LABELS[group.agent] ?? group.agent;
              return (
                <div key={group.agent + group.items[0].created_at}>
                  {/* Agent group header */}
                  <div className="flex items-center gap-2 px-2 py-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: agentColor }}
                    />
                    <span
                      className="font-label-caps text-[10px] tracking-wide"
                      style={{ color: agentColor }}
                    >
                      {agentLabel}
                    </span>
                    <span className="flex-1 h-px bg-outline-variant/20" />
                    <span className="font-code-xs text-[10px] text-on-surface-variant/40">
                      {group.items.length}
                    </span>
                  </div>

                  {/* Tool calls — compact rows */}
                  {group.items.map((tc, tcLocalIdx) => {
                    const meta = getToolMeta(tc.tool_name);
                    const catStyle = getCategoryStyle(meta.category);
                    const isError = tc.tool_status === "error";
                    const tcIdx = sorted.indexOf(tc);
                    // Use composite key to avoid duplicates when same tool appears multiple times
                    const uniqueKey = `${tc.agent_name}-${tc.tool_name}-${tc.created_at}-${tcLocalIdx}`;
                    return (
                      <div
                        key={uniqueKey}
                        className="ml-2 border-l-2 rounded-r-md"
                        style={{ borderLeftColor: catStyle.border }}
                      >
                        {/* Compact main row */}
                        <div
                          className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-surface-container-high/30 transition-colors rounded-r-md"
                          onClick={() => setExpandedId(expandedId === tcIdx ? null : tcIdx)}
                        >
                          <span
                            className="material-symbols-outlined text-[13px] flex-shrink-0"
                            style={{ color: catStyle.text }}
                          >
                            {meta.icon}
                          </span>
                          <span className="font-body-xs text-on-surface flex-1 min-w-0 truncate">
                            {isError && <span className="text-error mr-0.5">!</span>}
                            {meta.label}
                          </span>
                          {tc.tool_latency_ms !== null && (
                            <span className="font-code-xs text-[10px] text-on-surface-variant/50 flex-shrink-0">
                              {formatDuration(tc.tool_latency_ms)}
                            </span>
                          )}
                          <span
                            className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                              isError ? "bg-error" : "bg-primary-container/60"
                            }`}
                          />
                          <span className="material-symbols-outlined text-[12px] text-on-surface-variant/30 flex-shrink-0">
                            {expandedId === tcIdx ? "expand_less" : "expand_more"}
                          </span>
                        </div>

                        {/* Expandable details */}
                        {expandedId === tcIdx && (
                          <div className="px-3 pb-2 pt-0 ml-2">
                            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] mt-1">
                              <div>
                                <span className="text-on-surface-variant/40">Tool: </span>
                                <span className="font-code-xs text-on-surface-variant/70">{tc.tool_name}</span>
                              </div>
                              <div>
                                <span className="text-on-surface-variant/40">Status: </span>
                                <span className={`font-code-xs ${isError ? "text-error" : "text-primary-container/80"}`}>
                                  {tc.tool_status ?? "unknown"}
                                </span>
                              </div>
                              {tc.tool_latency_ms !== null && (
                                <div>
                                  <span className="text-on-surface-variant/40">Duration: </span>
                                  <span className="font-code-xs text-on-surface-variant/70">{tc.tool_latency_ms}ms</span>
                                </div>
                              )}
                              {tc.created_at && (
                                <div>
                                  <span className="text-on-surface-variant/40">Time: </span>
                                  <span className="font-code-xs text-on-surface-variant/70">
                                    {new Date(tc.created_at).toLocaleTimeString()}
                                  </span>
                                </div>
                              )}
                            </div>
                            <div className="mt-1.5">
                              <span
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-label-caps"
                                style={{
                                  backgroundColor: catStyle.bg,
                                  color: catStyle.text,
                                  border: `1px solid ${catStyle.border}`,
                                }}
                              >
                                {meta.category}
                              </span>
                            </div>
                            {tc.tool_input && (
                              <div className="mt-2">
                                <span className="text-[10px] text-on-surface-variant/40 font-label-caps">Input</span>
                                <pre className="mt-0.5 p-2 bg-surface-container-low rounded-md text-[10px] font-code-xs text-on-surface-variant/70 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap break-all">
                                  {tc.tool_input}
                                </pre>
                              </div>
                            )}
                            {tc.tool_output && (
                              <div className="mt-2">
                                <span className="text-[10px] text-on-surface-variant/40 font-label-caps">Output</span>
                                <pre className="mt-0.5 p-2 bg-surface-container-low rounded-md text-[10px] font-code-xs text-on-surface-variant/70 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap break-all">
                                  {tc.tool_output}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {/* Running indicator — inline */}
            {isRunning && (
              <div className="flex items-center gap-2 px-2 py-1.5">
                <span className="material-symbols-outlined text-[14px] text-primary-fixed-dim animate-spin">
                  progress_activity
                </span>
                <span className="font-body-xs text-on-surface-variant/60">
                  Working...
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
