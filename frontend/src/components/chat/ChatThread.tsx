import { useRef, useEffect, useCallback } from "react";
import type { AggregatedOutput, ReviewToolCallItem } from "../../types/api";
import FindingsList from "./FindingsList";
import EventFeed from "./EventFeed";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: AggregatedOutput;
  timestamp: string;
}

interface ChatThreadProps {
  messages: ChatMessage[];
  toolCalls?: ReviewToolCallItem[];
  isWorking?: boolean;
  conversationId?: number | null;
}

// Per-conversation scroll position store (module-level singleton)
const scrollPositions = new Map<number, number>();

export default function ChatThread({ messages, toolCalls = [], isWorking = false, conversationId }: ChatThreadProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);
  const prevMessageCount = useRef(messages.length);
  const prevToolCallCount = useRef(toolCalls.length);

  // Track scroll position — detect when user scrolls up vs auto-scroll
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    isUserScrolledUp.current = !atBottom;

    // Persist scroll position for this conversation
    if (conversationId != null) {
      scrollPositions.set(conversationId, el.scrollTop);
    }
  }, [conversationId]);

  // Restore scroll position when switching conversations
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || conversationId == null) return;

    const saved = scrollPositions.get(conversationId);
    if (saved !== undefined) {
      // Restore after render
      requestAnimationFrame(() => {
        el.scrollTop = saved;
        isUserScrolledUp.current = false;
      });
    } else {
      // New conversation — start at top
      el.scrollTop = 0;
      isUserScrolledUp.current = false;
    }
  }, [conversationId]);

  // Auto-scroll to bottom on new messages or tool calls (unless user scrolled up)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const newMessages = messages.length > prevMessageCount.current;
    const newToolCalls = toolCalls.length > prevToolCallCount.current;
    prevMessageCount.current = messages.length;
    prevToolCallCount.current = toolCalls.length;

    if ((newMessages || newToolCalls) && !isUserScrolledUp.current) {
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      });
    }
  }, [messages.length, toolCalls.length]);

  if (messages.length === 0 && !isWorking) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <div className="text-center">
          <span className="material-symbols-outlined text-outline text-[48px] mb-4 block">
            chat
          </span>
          <p className="font-body-md text-on-surface-variant">
            Start a conversation about your code
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto p-4 md:p-lg flex flex-col gap-4"
    >
      {messages.map((msg) => (
        <div key={msg.id} className="flex gap-4 max-w-4xl mx-auto w-full">
          <div
            className={`w-8 h-8 rounded flex-shrink-0 flex items-center justify-center ${
              msg.role === "user"
                ? "bg-surface-container-highest border border-outline-variant"
                : "bg-primary-container"
            }`}
          >
            <span
              className={`material-symbols-outlined text-[20px] ${
                msg.role === "user"
                  ? "text-on-surface-variant"
                  : "text-on-primary-fixed filled"
              }`}
            >
              {msg.role === "user" ? "person" : "robot_2"}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            {msg.role === "user" ? (
              <div className="bg-surface-container p-4 rounded-lg border border-outline-variant inline-block max-w-full">
                <p className="font-body-md text-on-surface whitespace-pre-wrap break-words">{msg.content}</p>
              </div>
            ) : (
              <div className="space-y-4">
                {msg.content.trim() && (
                  <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant">
                    <p className="font-body-md text-on-surface whitespace-pre-wrap break-words">{msg.content}</p>
                  </div>
                )}
                {msg.result && <FindingsList findings={msg.result.findings} parseStatus={msg.result.parse_status} />}
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Live agent working feed — bounded, scrollable */}
      {(toolCalls.length > 0 || isWorking) && (
        <div className="max-w-4xl mx-auto w-full">
          <EventFeed toolCalls={toolCalls} isRunning={isWorking} />
        </div>
      )}

      {/* Bottom spacer for composer */}
      <div className="h-4 flex-shrink-0" />
    </div>
  );
}
