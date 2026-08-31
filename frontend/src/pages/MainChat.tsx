import { useState, useCallback, useRef, useEffect } from "react";
import Sidebar from "../components/layout/Sidebar";
import TopBar from "../components/layout/TopBar";
import RepoDropdown from "../components/repo/RepoDropdown";
import BranchDropdown from "../components/repo/BranchDropdown";
import ChatThread, { type ChatMessage } from "../components/chat/ChatThread";
import MessageComposer from "../components/chat/MessageComposer";
import { useActiveRepo } from "../state/activeRepo";
import {
  useConversationCache,
  getReviewSessionId,
  setReviewSessionId,
  getPendingTurn,
  setPendingTurn,
  getToolCallsCache,
  setToolCallsCache,
  clearReviewState,
} from "../state/conversationCache";
import { useConversationState } from "../state/conversationState";
import { loadIdentity } from "../state/identity";
import { createConversation } from "../api/conversations";
import { getLatestReview } from "../api/reviewStatus";
import { useReviewTurn } from "../hooks/useReviewTurn";
import { useReviewProgress } from "../hooks/useReviewProgress";
import { formatAnswer } from "../utils/formatAnswer";
import type { RequestType, AggregatedOutput, ReviewToolCallItem } from "../types/api";

export default function MainChat() {
  const { repo_id, branch, selectRepo, selectBranch } = useActiveRepo();
  const { conversations, addConversation, removeConversation, renameConversation } = useConversationCache();
  const {
    activeConversationId,
    setActiveConversationId,
    messages,
    setMessages,
    switchConversation,
  } = useConversationState();
  const identity = loadIdentity();

  const { isWorking, error, preparing, sendTurn, retryPreparing, reset } = useReviewTurn();
  const { toolCalls, startPolling, stopPolling, setToolCalls } = useReviewProgress();

  const pendingTurnRef = useRef<{
    content: string;
    requestType: RequestType;
  } | null>(null);

  // Restore pendingTurn from localStorage on mount / conversation switch
  useEffect(() => {
    if (activeConversationId) {
      pendingTurnRef.current = getPendingTurn(activeConversationId);
    }
  }, [activeConversationId]);

  // Cleanup: save tool calls to cache on unmount or conversation switch
  const prevConversationIdRef = useRef<number | null>(null);
  useEffect(() => {
    const prevId = prevConversationIdRef.current;
    if (prevId !== null && prevId !== activeConversationId) {
      // Save tool calls for the previous conversation
      setToolCallsCache(prevId, toolCalls);
    }
    prevConversationIdRef.current = activeConversationId;

    return () => {
      // On unmount: save current tool calls
      if (activeConversationId) {
        setToolCallsCache(activeConversationId, toolCalls);
      }
    };
  }, [activeConversationId, toolCalls]);

  // Restore tool calls from cache on conversation switch
  useEffect(() => {
    if (activeConversationId) {
      const cached = getToolCallsCache(activeConversationId);
      setToolCalls(cached);
    }
  }, [activeConversationId, setToolCalls]);

  // --- Reconnection on mount: detect orphaned review ---
  useEffect(() => {
    if (!activeConversationId || !identity) return;

    // Only reconnect if the last message is a user message with no assistant response
    const lastMsg = messages[messages.length - 1];
    if (!lastMsg || lastMsg.role !== "user") return;

    // Check if there's a stored review_session_id OR if messages suggest an orphaned review
    const storedSessionId = getReviewSessionId(activeConversationId);
    // Even without stored session ID, try fetching — the backend may have the review

    // There's an orphaned review — fetch its status
    let cancelled = false;
    (async () => {
      try {
        const latest = await getLatestReview(activeConversationId, identity.user_id);
        if (cancelled) return;

        if (latest.review_session_id === null) {
          // Review disappeared from DB — clear stale state
          clearReviewState(activeConversationId);
          return;
        }

        if (latest.status === "completed" && latest.result) {
          // Review completed while we were away — restore the result
          const assistantMsg: ChatMessage = {
            id: `assistant-reconnect-${Date.now()}`,
            role: "assistant",
            content: formatAnswer(latest.result),
            result: latest.result,
            timestamp: latest.completed_at ?? new Date().toISOString(),
          };
          setMessages((prev) => {
            // Avoid duplicate if already present
            const hasAssistant = prev.some((m) => m.role === "assistant" && m.id.startsWith("assistant-reconnect"));
            if (hasAssistant) return prev;
            return [...prev, assistantMsg];
          });
          // Restore tool calls from the completed review
          if (latest.tool_calls && latest.tool_calls.length > 0) {
            setToolCalls(latest.tool_calls);
          }
          clearReviewState(activeConversationId);
        } else if (latest.status === "failed") {
          // Review failed while we were away — show error
          setMessages((prev) => {
            const hasError = prev.some((m) => m.role === "assistant" && m.id.startsWith("assistant-reconnect"));
            if (hasError) return prev;
            return [...prev, {
              id: `assistant-reconnect-${Date.now()}`,
              role: "assistant",
              content: `Review failed: ${latest.error ?? "Unknown error"}. Please try again.`,
              timestamp: new Date().toISOString(),
            }];
          });
          clearReviewState(activeConversationId);
        } else if (latest.status === "running") {
          // Review still running — resume polling (preserve cached tool calls)
          startPolling(activeConversationId, identity.user_id, undefined, true);
        } else {
          // Unknown status — clear stale state
          clearReviewState(activeConversationId);
        }
      } catch {
        // Network error or 404 — clear stale state
        clearReviewState(activeConversationId);
      }
    })();

    return () => { cancelled = true; };
  }, [activeConversationId, identity, messages, setMessages, setToolCalls, startPolling]);

  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  const handleNewConversation = useCallback(async () => {
    if (!repo_id || !identity) return;

    try {
      const conv = await createConversation(repo_id, identity.user_id);
      setActiveConversationId(conv.conversation_id);
      addConversation({
        conversation_id: conv.conversation_id,
        repo_id,
        title: "New conversation",
        created_at: new Date().toISOString(),
      });
      setMessages([]);
      setToolCalls([]);
      reset();
    } catch (e) {
      console.error("Failed to create conversation:", e);
    }
  }, [repo_id, identity, addConversation, reset, setActiveConversationId, setMessages, setToolCalls]);

  const handleSelectConversation = useCallback((conversationId: number) => {
    stopPolling();
    switchConversation(conversationId);
    setToolCalls([]);
    reset();
  }, [stopPolling, switchConversation, setToolCalls, reset]);

  const handleDeleteConversation = useCallback((conversationId: number) => {
    removeConversation(conversationId);
    const userId = identity?.user_id ?? "anonymous";
    localStorage.removeItem(`reviewmind_messages_v1_${userId}_${conversationId}`);
    clearReviewState(conversationId);
    if (activeConversationId === conversationId) {
      setActiveConversationId(null);
      setMessages([]);
      setToolCalls([]);
    }
  }, [removeConversation, activeConversationId, setActiveConversationId, setMessages, setToolCalls]);

  const handleSend = useCallback(
    async (content: string, requestType: RequestType) => {
      if (!repo_id || !branch || !identity || !activeConversationId) return;

      const userMsg = {
        id: `user-${Date.now()}`,
        role: "user" as const,
        content,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      pendingTurnRef.current = { content, requestType };
      setPendingTurn(activeConversationId, { content, requestType });

      startPolling(activeConversationId, identity.user_id, (sessionId) => {
        // Persist review_session_id as soon as polling discovers it
        setReviewSessionId(activeConversationId, sessionId);
      });

      const turnResult = await sendTurn(
        activeConversationId,
        identity.user_id,
        repo_id,
        content,
        requestType,
        branch,
      );

      stopPolling();

      if (turnResult) {
        // Persist review_session_id for reconnection after navigation
        setReviewSessionId(activeConversationId, turnResult.response.review_session_id);

        const assistantMsg: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: formatAnswer(turnResult.result),
          result: turnResult.result,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setToolCalls([]);
        pendingTurnRef.current = null;
        setPendingTurn(activeConversationId, null);
        clearReviewState(activeConversationId);
      }
    },
    [repo_id, branch, identity, activeConversationId, sendTurn, startPolling, stopPolling, setMessages, setToolCalls],
  );

  const handleRetryPreparing = useCallback(async () => {
    if (!pendingTurnRef.current || !repo_id || !branch || !identity || !activeConversationId) return;

    const { content, requestType } = pendingTurnRef.current;

    startPolling(activeConversationId, identity.user_id, (sessionId) => {
      setReviewSessionId(activeConversationId, sessionId);
    });

    const result = await retryPreparing(
      activeConversationId,
      identity.user_id,
      repo_id,
      content,
      requestType,
      branch,
    );

    stopPolling();

    if (result) {
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: formatAnswer(result.result),
        result: result.result,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setToolCalls([]);
      pendingTurnRef.current = null;
      setPendingTurn(activeConversationId, null);
      clearReviewState(activeConversationId);
    }
  }, [repo_id, branch, identity, activeConversationId, retryPreparing, startPolling, stopPolling, setMessages, setToolCalls]);

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <Sidebar
        conversations={conversations}
        onNewConversation={handleNewConversation}
        onSelectConversation={handleSelectConversation}
        onRenameConversation={renameConversation}
        onDeleteConversation={handleDeleteConversation}
      />

      <TopBar>
        <RepoDropdown selectedRepoId={repo_id} onSelect={selectRepo} />
        <BranchDropdown
          repoId={repo_id}
          selectedBranch={branch}
          onSelect={selectBranch}
        />
      </TopBar>

      {/* Main content — flex column, sidebar offset on desktop */}
      <div className="flex-1 flex flex-col md:ml-[280px] mt-16 min-h-0 bg-surface-dim">
        {/* Chat area — flex-1, scrollable, no overflow hidden on parent */}
        <ChatThread
          messages={messages}
          toolCalls={toolCalls}
          isWorking={isWorking}
          conversationId={activeConversationId}
        />

        {/* Preparing state — 425 graph not ready */}
        {preparing && (
          <div className="px-4 md:px-lg py-4 flex-shrink-0">
            <div className="max-w-4xl mx-auto w-full">
              <div className="bg-surface-container border border-outline-variant rounded-lg p-4 flex items-center gap-4">
                <span className="material-symbols-outlined text-primary-fixed-dim animate-spin">
                  progress_activity
                </span>
                <div className="flex-1">
                  <p className="font-body-md text-on-surface">
                    Preparing this branch... The graph is being built.
                  </p>
                  <p className="font-body-sm text-on-surface-variant mt-1">
                    This may take a few minutes on first use.
                  </p>
                </div>
                <button
                  onClick={handleRetryPreparing}
                  className="bg-primary-container text-on-primary-container font-label-caps text-label-caps px-md py-sm rounded font-bold hover:bg-primary-fixed transition-colors"
                >
                  Retry
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="px-4 md:px-lg py-4 flex-shrink-0">
            <div className="max-w-4xl mx-auto w-full">
              <div className="bg-surface-container border border-error/30 rounded-lg p-4 flex items-center gap-4">
                <span className="material-symbols-outlined text-error">error</span>
                <div className="flex-1">
                  <p className="font-body-md text-on-surface">Something went wrong</p>
                  <p className="font-body-sm text-on-surface-variant mt-1">{error}</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Composer — flex child, not absolute */}
        <div className="flex-shrink-0 border-t border-outline-variant/40 bg-surface/90 backdrop-blur-md">
          <MessageComposer
            onSend={handleSend}
            disabled={!repo_id || !branch || !identity || !activeConversationId || isWorking}
          />
        </div>
      </div>
    </div>
  );
}
