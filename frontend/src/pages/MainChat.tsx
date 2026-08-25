import { useState, useCallback, useRef, useEffect } from "react";
import Sidebar from "../components/layout/Sidebar";
import TopBar from "../components/layout/TopBar";
import RepoDropdown from "../components/repo/RepoDropdown";
import BranchDropdown from "../components/repo/BranchDropdown";
import ChatThread, { type ChatMessage } from "../components/chat/ChatThread";
import MessageComposer from "../components/chat/MessageComposer";
import { useActiveRepo } from "../state/activeRepo";
import { useConversationCache } from "../state/conversationCache";
import { loadIdentity } from "../state/identity";
import { createConversation } from "../api/conversations";
import { useReviewTurn } from "../hooks/useReviewTurn";
import { useReviewProgress } from "../hooks/useReviewProgress";
import type { RequestType, AggregatedOutput } from "../types/api";

export default function MainChat() {
  const { repo_id, branch, selectRepo, selectBranch } = useActiveRepo();
  const { conversations, addConversation } = useConversationCache();
  const identity = loadIdentity();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);

  const { isWorking, error, preparing, sendTurn, retryPreparing, reset } = useReviewTurn();
  const { toolCalls, startPolling, stopPolling, setToolCalls } = useReviewProgress();

  // Refs to hold the current turn's data for retry
  const pendingTurnRef = useRef<{
    content: string;
    requestType: RequestType;
  } | null>(null);

  // Cleanup polling on unmount
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
  }, [repo_id, identity, addConversation, reset]);

  const handleSend = useCallback(
    async (content: string, requestType: RequestType) => {
      if (!repo_id || !branch || !identity || !activeConversationId) return;

      // Optimistic user bubble
      const userMsg = {
        id: `user-${Date.now()}`,
        role: "user" as const,
        content,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      // Store for retry if we get 425
      pendingTurnRef.current = { content, requestType };

      // Start polling concurrently — runs alongside the review
      startPolling(activeConversationId, identity.user_id);

      // The two-call sequence (Section 2)
      const result = await sendTurn(
        activeConversationId,
        identity.user_id,
        repo_id,
        content,
        requestType,
        branch,
      );

      // Stop polling — sendTurn's response is the final answer
      stopPolling();

      if (result) {
        // Parse the result — this is the assistant's chat bubble
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
      }
      // If null, either 425 (preparing state) or error — UI already shows it
    },
    [repo_id, branch, identity, activeConversationId, sendTurn, startPolling, stopPolling],
  );

  const handleRetryPreparing = useCallback(async () => {
    if (!pendingTurnRef.current || !repo_id || !branch || !identity || !activeConversationId) return;

    const { content, requestType } = pendingTurnRef.current;

    // Start polling again
    startPolling(activeConversationId, identity.user_id);

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
    }
  }, [repo_id, branch, identity, activeConversationId, retryPreparing, startPolling, stopPolling]);

  return (
    <div className="min-h-screen bg-background">
      <Sidebar
        conversations={conversations}
        onNewConversation={handleNewConversation}
      />

      <TopBar>
        <RepoDropdown selectedRepoId={repo_id} onSelect={selectRepo} />
        <BranchDropdown
          repoId={repo_id}
          selectedBranch={branch}
          onSelect={selectBranch}
        />
      </TopBar>

      {/* Main content area — full width on mobile, offset by sidebar on desktop */}
      <main className="md:ml-[280px] mt-16 h-[calc(100vh-64px)] flex flex-col relative bg-surface-dim">
        {/* ChatThread now handles the event feed inline */}
        <ChatThread
          messages={messages}
          toolCalls={toolCalls}
          isWorking={isWorking}
        />

        {/* Preparing state — 425 graph not ready */}
        {preparing && (
          <div className="px-4 md:px-lg py-4">
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
          <div className="px-4 md:px-lg py-4">
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

        <MessageComposer
          onSend={handleSend}
          disabled={!repo_id || !branch || !identity || !activeConversationId || isWorking}
        />
      </main>
    </div>
  );
}

// Format the parsed AggregatedOutput into readable text
function formatAnswer(result: AggregatedOutput): string {
  const parts: string[] = [];

  if (result.parse_status !== "ok") {
    parts.push(`⚠️ Parse status: ${result.parse_status}`);
  }

  if (result.findings.length === 0) {
    parts.push("No findings to report.");
  }

  return parts.join("\n");
}
