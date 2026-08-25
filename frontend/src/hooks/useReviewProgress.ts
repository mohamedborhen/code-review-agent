import { useState, useCallback, useRef, useEffect } from "react";
import { getRunningReview, getReviewStatus } from "../api/reviewStatus";
import type { ReviewToolCallItem } from "../types/api";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Polls tool_calls while a review runs (Section 2/4, supplementary — never the answer source)
// Runs CONCURRENTLY with sendTurn. Caller stops via abort.
export function useReviewProgress() {
  const [toolCalls, setToolCalls] = useState<ReviewToolCallItem[]>([]);
  const [isPolling, setIsPolling] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const startPolling = useCallback((conversationId: number, userId: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setToolCalls([]);
    setIsPolling(true);

    (async () => {
      let sessionId: number | null = null;

      // Phase 1: poll /reviews/running until we get a session_id
      while (!controller.signal.aborted && sessionId === null) {
        try {
          const running = await getRunningReview(conversationId, userId);
          sessionId = running.review_session_id;
          if (sessionId === null) {
            await sleep(1500); // review row not committed yet — small window, retry
          }
        } catch {
          if (controller.signal.aborted) break;
          await sleep(2000);
        }
      }

      // Phase 2: poll /reviews/{sessionId} for live tool_calls
      while (!controller.signal.aborted && sessionId !== null) {
        try {
          const status = await getReviewStatus(sessionId, userId);

          // Best-effort list; gaps expected. NOT guaranteed ordered — sort client-side.
          const ordered = [...status.tool_calls].sort(
            (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""),
          );
          setToolCalls(ordered);

          // Stop when the review is no longer running — sendTurn's response is authoritative
          if (status.status !== "running") break;

          await sleep(2500);
        } catch {
          if (controller.signal.aborted) break;
          await sleep(2500);
        }
      }

      setIsPolling(false);
    })();
  }, []);

  const stopPolling = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsPolling(false);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { toolCalls, isPolling, startPolling, stopPolling, setToolCalls };
}
