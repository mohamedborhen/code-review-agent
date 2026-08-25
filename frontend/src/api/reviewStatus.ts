import { apiFetch } from "./client";
import type { RunningReviewResponse, ReviewStatusResponse } from "../types/api";

// GET /api/v1/reviews/running?conversation_id={int}&user_id={str}
// §2: both params required. No-match: {review_session_id: null, status: null}
// ⚠️ The no-match branch omits `created_at` entirely (review.py:282)
export async function getRunningReview(
  conversationId: number,
  userId: string,
): Promise<RunningReviewResponse> {
  return apiFetch<RunningReviewResponse>(
    `/reviews/running?conversation_id=${conversationId}&user_id=${encodeURIComponent(userId)}`,
  );
}

// GET /api/v1/reviews/{session_id}?user_id={str}
// §2: user_id required. 404 if session_id doesn't exist OR user_id mismatch.
// tool_calls: exactly 5 keys per item, NO ORDER BY — sort client-side on created_at
// ⚠️ `result` is an already-parsed dict here (unlike POST /review where it's a string)
export async function getReviewStatus(
  sessionId: number,
  userId: string,
): Promise<ReviewStatusResponse> {
  return apiFetch<ReviewStatusResponse>(
    `/reviews/${sessionId}?user_id=${encodeURIComponent(userId)}`,
  );
}
