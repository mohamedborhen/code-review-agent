import { useState } from "react";
import type { RequestType } from "../../types/api";

const REQUEST_TYPES: { label: string; value: RequestType }[] = [
  { label: "Any Question", value: "any_question" },
  { label: "Full Review", value: "review" },
  { label: "Security Audit", value: "security_question" },
  { label: "Compliance Check", value: "compliance_question" },
  { label: "Performance", value: "performance_question" },
  { label: "Impact Analysis", value: "impact_question" },
  { label: "Explain Code", value: "explain_question" },
];

interface MessageComposerProps {
  onSend: (content: string, requestType: RequestType) => void;
  disabled?: boolean;
}

export default function MessageComposer({ onSend, disabled }: MessageComposerProps) {
  const [content, setContent] = useState("");
  const [requestType, setRequestType] = useState<RequestType>("any_question");
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const selectedLabel = REQUEST_TYPES.find((r) => r.value === requestType)?.label ?? "Any Question";

  function handleSend() {
    if (!content.trim() || disabled) return;
    onSend(content.trim(), requestType);
    setContent("");
  }

  return (
    <div className="p-2 md:p-4">
      <div className="max-w-4xl mx-auto relative">
        <div className="bg-surface-container border border-outline-variant rounded-lg p-2 focus-within:border-primary-fixed-dim focus-within:shadow-[0_0_8px_rgba(0,220,229,0.2)] transition-all duration-200">
          {/* Request type selector */}
          <div className="flex items-center gap-2 px-2 pb-2 border-b border-outline-variant mb-2">
            <div className="relative">
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="flex items-center gap-1 text-on-surface-variant hover:text-primary-fixed-dim text-sm font-medium transition-colors bg-surface-container-highest px-2 py-1 rounded"
              >
                <span className="material-symbols-outlined text-[18px]">search</span>
                <span className="hidden sm:inline">{selectedLabel}</span>
                <span className="sm:hidden text-xs">{selectedLabel.split(" ")[0]}</span>
                <span className="material-symbols-outlined text-[16px]">arrow_drop_down</span>
              </button>

              {dropdownOpen && (
                <div className="absolute bottom-full left-0 mb-1 w-56 bg-surface-container border border-outline-variant rounded-lg shadow-lg z-50 py-1">
                  {REQUEST_TYPES.map((rt) => (
                    <button
                      key={rt.value}
                      onClick={() => {
                        setRequestType(rt.value);
                        setDropdownOpen(false);
                      }}
                      className={`w-full text-left px-4 py-2 font-body-sm text-body-sm hover:bg-surface-container-high transition-colors ${
                        rt.value === requestType
                          ? "text-primary-fixed-dim bg-surface-container-high"
                          : "text-on-surface"
                      }`}
                    >
                      {rt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Text input */}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            className="w-full bg-transparent text-on-surface font-body-md p-2 outline-none resize-none border-none focus:ring-0 placeholder-on-surface-variant/50 min-h-[48px] md:min-h-[60px]"
            placeholder="Ask a question about the code..."
            disabled={disabled}
          />

          {/* Actions */}
          <div className="flex items-center justify-end px-2 pt-2">
            <button
              onClick={handleSend}
              disabled={!content.trim() || disabled}
              className="bg-primary-container text-on-primary-fixed p-2 rounded-full hover:bg-primary-fixed transition-colors flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined filled">send</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
