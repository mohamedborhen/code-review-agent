// Local conversation cache — localStorage for 5a (IndexedDB in 5b).
// Identity-scoped: each user_id has its own conversation list.
import { useState, useCallback, useEffect } from "react";
import { loadIdentity } from "./identity";
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

export function setReviewSessionId(conversationId: number, sessionId: number | null): void {
  if (sessionId === null) {
    localStorage.removeItem(`reviewmind_review_session_v1_${conversationId}`);
  } else {
    localStorage.setItem(`reviewmind_review_session_v1_${conversationId}`, String(sessionId));
  }
}

export function getReviewSessionId(conversationId: number): number | null {
  const raw = localStorage.getItem(`reviewmind_review_session_v1_${conversationId}`);
  if (raw === null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function setPendingTurn(conversationId: number, turn: PendingTurn | null): void {
  if (turn === null) {
    localStorage.removeItem(`reviewmind_pending_turn_v1_${conversationId}`);
  } else {
    localStorage.setItem(`reviewmind_pending_turn_v1_${conversationId}`, JSON.stringify(turn));
  }
}

export function getPendingTurn(conversationId: number): PendingTurn | null {
  try {
    const raw = localStorage.getItem(`reviewmind_pending_turn_v1_${conversationId}`);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setToolCallsCache(conversationId: number, toolCalls: ReviewToolCallItem[]): void {
  localStorage.setItem(`reviewmind_tool_calls_v1_${conversationId}`, JSON.stringify(toolCalls));
}

export function getToolCallsCache(conversationId: number): ReviewToolCallItem[] {
  try {
    const raw = localStorage.getItem(`reviewmind_tool_calls_v1_${conversationId}`);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function clearReviewState(conversationId: number): void {
  localStorage.removeItem(`reviewmind_review_session_v1_${conversationId}`);
  localStorage.removeItem(`reviewmind_pending_turn_v1_${conversationId}`);
  localStorage.removeItem(`reviewmind_tool_calls_v1_${conversationId}`);
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
