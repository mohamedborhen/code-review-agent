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
}

export default function ChatThread({ messages, toolCalls = [], isWorking = false }: ChatThreadProps) {
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
    <div className="flex-1 overflow-y-auto p-4 md:p-lg flex flex-col gap-margin pb-[120px]">
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
                <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant">
                  <p className="font-body-md text-on-surface whitespace-pre-wrap break-words">{msg.content}</p>
                </div>
                {msg.result && <FindingsList findings={msg.result.findings} parseStatus={msg.result.parse_status} />}
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Live agent working feed — renders inline after the last message */}
      {(toolCalls.length > 0 || isWorking) && (
        <EventFeed toolCalls={toolCalls} isRunning={isWorking} />
      )}
    </div>
  );
}
