import type { AggregatedOutput } from "../types/api";

/**
 * Format an AggregatedOutput into a human-readable content string.
 * Extracted from MainChat.tsx for reuse in account restore.
 */
export function formatAnswer(result: AggregatedOutput): string {
  if (result.parse_status !== "ok") {
    return result.findings.length === 0
      ? `Parse status: ${result.parse_status}`
      : `Parse status: ${result.parse_status}\nReview completed with ${result.findings.length} finding(s).`;
  }

  if (result.findings.length === 0) {
    return "No findings to report.";
  }

  return `Review completed with ${result.findings.length} finding(s).`;
}
