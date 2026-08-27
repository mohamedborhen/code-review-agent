// Conversation state persistence — stores messages and active conversation ID in localStorage.
import { useState, useCallback, useEffect, useRef } from "react";
import type { ChatMessage } from "../components/chat/ChatThread";

const ACTIVE_CONV_KEY = "reviewmind_active_conversation_v1";
const MESSAGES_KEY_PREFIX = "reviewmind_messages_v1_";

export interface ConversationState {
  activeConversationId: number | null;
  messages: ChatMessage[];
}

function loadActiveConversationId(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_CONV_KEY);
    if (!raw) return null;
    const id = parseInt(raw, 10);
    return isNaN(id) ? null : id;
  } catch {
    return null;
  }
}

function saveActiveConversationId(id: number | null): void {
  try {
    if (id === null) {
      localStorage.removeItem(ACTIVE_CONV_KEY);
    } else {
      localStorage.setItem(ACTIVE_CONV_KEY, String(id));
    }
  } catch {
    // ignore
  }
}

function loadMessages(conversationId: number): ChatMessage[] {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY_PREFIX + conversationId);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveMessages(conversationId: number, messages: ChatMessage[]): void {
  try {
    localStorage.setItem(MESSAGES_KEY_PREFIX + conversationId, JSON.stringify(messages));
  } catch {
    // ignore — localStorage full or unavailable
  }
}

export function useConversationState() {
  const [activeConversationId, setActiveConversationId] = useState<number | null>(loadActiveConversationId);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    activeConversationId !== null ? loadMessages(activeConversationId) : []
  );

  // Persist active conversation ID on change
  useEffect(() => {
    saveActiveConversationId(activeConversationId);
  }, [activeConversationId]);

  // Persist messages on change (debounced)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (activeConversationId === null) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      saveMessages(activeConversationId, messages);
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [activeConversationId, messages]);

  const switchConversation = useCallback((conversationId: number) => {
    setActiveConversationId(conversationId);
    setMessages(loadMessages(conversationId));
  }, []);

  const clearActiveConversation = useCallback(() => {
    setActiveConversationId(null);
    setMessages([]);
  }, []);

  return {
    activeConversationId,
    setActiveConversationId,
    messages,
    setMessages,
    switchConversation,
    clearActiveConversation,
  };
}
