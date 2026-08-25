import { useState, useCallback, useRef } from "react";
import { postConversationMessage } from "../api/conversations";
import { postReview } from "../api/review";
import type { RequestType, ReviewResponse, AggregatedOutput } from "../types/api";

export interface ReviewTurnState {
  isWorking: boolean;
  error: string | null;
  preparing: boolean; // 425 — graph not ready
}

// The two-call send sequence (Section 2's most error-prone rule)
// This is the ONLY place it lives.
export function useReviewTurn() {
  const [state, setState] = useState<ReviewTurnState>({
    isWorking: false,
    error: null,
    preparing: false,
  });
  const abortRef = useRef<AbortController | null>(null);

  const sendTurn = useCallback(
    async (
      conversationId: number,
      userId: string,
      repoId: string,
      content: string,
      requestType: RequestType,
      branch: string,
    ): Promise<{ response: ReviewResponse; result: AggregatedOutput } | null> => {
      const controller = new AbortController();
      abortRef.current = controller;

      setState({ isWorking: true, error: null, preparing: false });

      try {
        // Step 1: POST /api/v1/conversations/{conversationId}/message
        // Persists the message + runs recall. Its return is NOT the reply.
        await postConversationMessage(conversationId, {
          user_id: userId,
          repo_id: repoId,
          content,
        });

        // Step 2: POST /api/v1/review — the only call that answers the user
        const response = await postReview({
          repo_id: repoId,
          branch,
          request_type: requestType,
          question: content,
          conversation_id: conversationId,
          user_id: userId,
          // diff_content deliberately omitted — no UI path in Phase 5
        });

        // `result` is a JSON STRING on this endpoint (review.py:228) — parse it
        const result: AggregatedOutput = JSON.parse(response.result);

        setState({ isWorking: false, error: null, preparing: false });
        return { response, result };
      } catch (err: unknown) {
        if (controller.signal.aborted) return null;

        // Handle 425 — graph/branch not ready
        if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 425) {
          setState({ isWorking: false, error: null, preparing: true });
          return null;
        }

        const message = err instanceof Error ? err.message : "An unexpected error occurred";
        setState({ isWorking: false, error: message, preparing: false });
        return null;
      } finally {
        abortRef.current = null;
      }
    },
    [],
  );

  const retryPreparing = useCallback(
    async (
      conversationId: number,
      userId: string,
      repoId: string,
      content: string,
      requestType: RequestType,
      branch: string,
    ): Promise<{ response: ReviewResponse; result: AggregatedOutput } | null> => {
      setState({ isWorking: true, error: null, preparing: false });
      try {
        const response = await postReview({
          repo_id: repoId,
          branch,
          request_type: requestType,
          question: content,
          conversation_id: conversationId,
          user_id: userId,
        });

        const result: AggregatedOutput = JSON.parse(response.result);
        setState({ isWorking: false, error: null, preparing: false });
        return { response, result };
      } catch (err: unknown) {
        if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 425) {
          setState({ isWorking: false, error: null, preparing: true });
          return null;
        }
        const message = err instanceof Error ? err.message : "An unexpected error occurred";
        setState({ isWorking: false, error: message, preparing: false });
        return null;
      }
    },
    [],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState({ isWorking: false, error: null, preparing: false });
  }, []);

  return { ...state, sendTurn, retryPreparing, reset };
}
