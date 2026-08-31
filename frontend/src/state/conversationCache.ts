// Local conversation cache — localStorage for 5a (IndexedDB in 5b).
// Identity-scoped: each user_id has its own conversation list.
import { useState, useCallback, useEffect } from "react";
import { loadIdentity } from "./identity";
import { apiFetch } from "../api/client";
import type { RequestType, ReviewToolCallItem } from "../types/api";

export interface ConversationMeta {
  conversation_id: number;
  repo_id: string;
  title: string;
  created_at: string;
}

export interface PendingTurn {
  content: string;
  requestType: RequestType;
}

const STORAGE_KEY_PREFIX = "reviewmind_conversations_v1_";

function getStorageKey(): string {
  const identity = loadIdentity();
  return STORAGE_KEY_PREFIX + (identity?.user_id ?? "anonymous");
}

function loadConversations(): ConversationMeta[] {
  try {
    const raw = localStorage.getItem(getStorageKey());
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveConversations(list: ConversationMeta[]): void {
  localStorage.setItem(getStorageKey(), JSON.stringify(list));
}

// --- Per-conversation review persistence (survives unmounts) ---

function getPerConversationKey(suffix: string, conversationId: number): string {
  const identity = loadIdentity();
  return `reviewmind_${suffix}_v1_${identity?.user_id ?? "anonymous"}_${conversationId}`;
}

export function setReviewSessionId(conversationId: number, sessionId: number | null): void {
  const key = getPerConversationKey("review_session", conversationId);
  if (sessionId === null) {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, String(sessionId));
  }
}

export function getReviewSessionId(conversationId: number): number | null {
  const raw = localStorage.getItem(getPerConversationKey("review_session", conversationId));
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function setPendingTurn(conversationId: number, turn: PendingTurn | null): void {
  const key = getPerConversationKey("pending_turn", conversationId);
  if (turn === null) {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, JSON.stringify(turn));
  }
}

export function getPendingTurn(conversationId: number): PendingTurn | null {
  try {
    const raw = localStorage.getItem(getPerConversationKey("pending_turn", conversationId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setToolCallsCache(conversationId: number, toolCalls: ReviewToolCallItem[]): void {
  localStorage.setItem(getPerConversationKey("tool_calls", conversationId), JSON.stringify(toolCalls));
}

export function getToolCallsCache(conversationId: number): ReviewToolCallItem[] {
  try {
    const raw = localStorage.getItem(getPerConversationKey("tool_calls", conversationId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function clearReviewState(conversationId: number): void {
  localStorage.removeItem(getPerConversationKey("review_session", conversationId));
  localStorage.removeItem(getPerConversationKey("pending_turn", conversationId));
  localStorage.removeItem(getPerConversationKey("tool_calls", conversationId));
}

// --- Backend sync for account restore (Phase 5) ---

/**
 * Fetch conversations from backend and populate localStorage.
 * Used when restoring an account from another browser/session.
 */
export async function syncConversationsFromBackend(user_id: string): Promise<ConversationMeta[]> {
  try {
    const data = await apiFetch<{ conversations: Array<{
      conversation_id: number;
      repo_id: string;
      created_at: string | null;
      message_count: number;
    }> }>(`/accounts/conversations?user_id=${encodeURIComponent(user_id)}`);

    const backendConversations = data.conversations ?? [];

    // Map backend conversations to frontend format
    const conversations: ConversationMeta[] = backendConversations.map(
      (conv: {
        conversation_id: number;
        repo_id: string;
        created_at: string | null;
        message_count: number;
      }) => ({
        conversation_id: conv.conversation_id,
        repo_id: conv.repo_id,
        title: conv.repo_id.split("/").pop() ?? "Untitled", // Use repo name as default title
        created_at: conv.created_at ?? new Date().toISOString(),
      })
    );

    const existing = loadConversations();

    // If backend returns nothing, don't overwrite local data
    if (conversations.length === 0) {
      return existing;
    }

    const merged = [...existing];
    for (const conv of conversations) {
      const idx = merged.findIndex((c) => c.conversation_id === conv.conversation_id);
      if (idx >= 0) {
        merged[idx] = conv; // backend wins on conflict
      } else {
        merged.push(conv); // new from backend
      }
    }

    saveConversations(merged);
    return merged;
  } catch (error) {
    console.error("Failed to sync conversations from backend:", error);
    return [];
  }
}

export function useConversationCache() {
  const [conversations, setConversations] = useState<ConversationMeta[]>(
    loadConversations,
  );

  useEffect(() => {
    saveConversations(conversations);
  }, [conversations]);

  const addConversation = useCallback((c: ConversationMeta) => {
    setConversations((prev) => [c, ...prev.filter((p) => p.conversation_id !== c.conversation_id)]);
  }, []);

  const removeConversation = useCallback((id: number) => {
    clearReviewState(id);
    setConversations((prev) => prev.filter((c) => c.conversation_id !== id));
  }, []);

  const renameConversation = useCallback((id: number, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.conversation_id === id ? { ...c, title } : c)),
    );
  }, []);

  return { conversations, addConversation, removeConversation, renameConversation };
}
