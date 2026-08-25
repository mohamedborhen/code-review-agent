import { apiFetch } from "./client";
import type { ReviewRequest, ReviewResponse } from "../types/api";

// POST /api/v1/review — THIS is what actually answers the user
// §2: synchronous, blocks for the entire review duration
// ⚠️ `result` is a JSON STRING here (review.py:228) — must JSON.parse()
// Returns 425 if graph not ready (branch not built yet)
// Returns 400, 404, 500 for various errors
export async function postReview(
  req: ReviewRequest,
): Promise<ReviewResponse> {
  return apiFetch<ReviewResponse>("/review", {
    method: "POST",
    body: JSON.stringify(req),
  });
}
