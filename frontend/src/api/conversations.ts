import { apiFetch } from "./client";
import type { CreateConversationResponse, MessageTurnResponse } from "../types/api";

// POST /api/v1/conversations — exactly 4 keys (conversation.py:64-69)
// §2: { repo_id, user_id } → { conversation_id, repo_id, user_id, status }
export async function createConversation(
  repoId: string,
  userId: string,
): Promise<CreateConversationResponse> {
  return apiFetch<CreateConversationResponse>("/conversations", {
    method: "POST",
    body: JSON.stringify({ repo_id: repoId, user_id: userId }),
  });
}

// POST /api/v1/conversations/{conversation_id}/message
// §2: persists user message + runs recall/evidence lookup
// ⚠️ This does NOT return an assistant answer — it returns context/tool_calls only
// Exactly 4 top-level keys (run_conversation_turn.py:101-106)
export async function postConversationMessage(
  conversationId: number,
  body: { user_id: string; repo_id: string; content: string },
): Promise<MessageTurnResponse> {
  return apiFetch<MessageTurnResponse>(`/conversations/${conversationId}/message`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
