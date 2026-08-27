import { useState, useRef, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useSidebar } from "../../state/sidebar";

interface SidebarProps {
  conversations?: { conversation_id: number; title: string; repo_id: string }[];
  onNewConversation?: () => void;
  onSelectConversation?: (id: number) => void;
  onRenameConversation?: (id: number, title: string) => void;
  onDeleteConversation?: (id: number) => void;
}

export default function Sidebar({
  conversations = [],
  onNewConversation,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
}: SidebarProps) {
  const location = useLocation();
  const isSettings = location.pathname === "/settings";
  const { isOpen, close } = useSidebar();

  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renamingId !== null && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingId]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpenId(null);
      }
    }
    if (menuOpenId !== null) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [menuOpenId]);

  function handleRenameSubmit(id: number) {
    const trimmed = renameValue.trim();
    if (trimmed && onRenameConversation) {
      onRenameConversation(id, trimmed);
    }
    setRenamingId(null);
    setMenuOpenId(null);
  }

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-20 md:hidden"
          onClick={close}
        />
      )}

      <aside
        className={`fixed left-0 top-0 h-full w-[280px] bg-surface-container-low border-r border-outline-variant flex flex-col p-gutter z-30 transition-transform duration-200 ease-in-out
          md:translate-x-0
          ${isOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        {/* Brand */}
        <div className="mb-lg">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 bg-primary-container rounded flex items-center justify-center">
              <span className="material-symbols-outlined filled text-on-primary-fixed text-[20px]">
                psychology
              </span>
            </div>
            <div>
              <h1 className="font-headline-sm text-headline-sm font-bold text-primary-container">
                ReviewMind
              </h1>
              <p className="font-label-caps text-label-caps text-on-surface-variant opacity-70">
                AI-Powered Code Intelligence
              </p>
            </div>
          </div>
        </div>

        {/* New Conversation CTA */}
        <button
          onClick={() => {
            onNewConversation?.();
            close();
          }}
          className="w-full mb-lg flex items-center justify-center gap-2 border border-primary-fixed-dim text-primary-fixed-dim hover:bg-primary-fixed-dim/10 py-2 rounded transition-colors font-label-caps text-label-caps"
        >
          <span className="material-symbols-outlined text-[18px]">add</span>
          New Conversation
        </button>

        {/* Past Conversations */}
        <div className="mb-lg flex-1 overflow-hidden flex flex-col">
          <h2 className="font-label-caps text-label-caps text-on-surface-variant opacity-70 mb-3 px-4">
            Past Conversations
          </h2>
          <div className="space-y-1 overflow-y-auto">
            {conversations.length === 0 && (
              <p className="font-body-sm text-on-surface-variant opacity-50 px-4 py-2">
                No conversations yet
              </p>
            )}
            {conversations.map((c) => (
              <div
                key={c.conversation_id}
                className="group px-4 py-2 rounded hover:bg-surface-container-high cursor-pointer transition-colors"
              >
                {renamingId === c.conversation_id ? (
                  <input
                    ref={renameInputRef}
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => handleRenameSubmit(c.conversation_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleRenameSubmit(c.conversation_id);
                      if (e.key === "Escape") {
                        setRenamingId(null);
                        setMenuOpenId(null);
                      }
                    }}
                    className="w-full bg-surface-container-highest border border-primary-container rounded px-2 py-0.5 text-body-sm text-on-surface focus:outline-none"
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <div
                    onClick={() => {
                      onSelectConversation?.(c.conversation_id);
                      close();
                    }}
                    className="flex items-center justify-between"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-body-sm text-on-surface truncate">{c.title}</p>
                      <span className="inline-block mt-1 px-1.5 py-0.5 bg-surface-container-highest text-[10px] font-label-caps rounded text-on-surface-variant">
                        {c.repo_id.split("/").pop()}
                      </span>
                    </div>
                    <div className="relative" ref={menuOpenId === c.conversation_id ? menuRef : undefined}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId(menuOpenId === c.conversation_id ? null : c.conversation_id);
                        }}
                        className="opacity-0 group-hover:opacity-100 text-on-surface-variant hover:text-on-surface p-1 rounded transition-opacity"
                      >
                        <span className="material-symbols-outlined text-[16px]">more_vert</span>
                      </button>
                      {menuOpenId === c.conversation_id && (
                        <div className="absolute right-0 top-full mt-1 w-36 bg-surface-container-high border border-outline-variant rounded-lg shadow-lg z-50 py-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setRenamingId(c.conversation_id);
                              setRenameValue(c.title);
                              setMenuOpenId(null);
                            }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-body-sm text-on-surface hover:bg-surface-container-highest transition-colors"
                          >
                            <span className="material-symbols-outlined text-[16px]">edit</span>
                            Rename
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              if (window.confirm("Delete this conversation?")) {
                                onDeleteConversation?.(c.conversation_id);
                              }
                              setMenuOpenId(null);
                            }}
                            className="w-full flex items-center gap-2 px-3 py-2 text-body-sm text-error hover:bg-surface-container-highest transition-colors"
                          >
                            <span className="material-symbols-outlined text-[16px]">delete</span>
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Footer navigation */}
        <div className="mt-auto pt-4 border-t border-outline-variant flex flex-col gap-1">
          <Link
            to="/settings"
            onClick={close}
            className={`flex items-center gap-3 px-4 py-2 transition-colors duration-150 rounded ${
              isSettings
                ? "bg-secondary-container text-on-secondary-container"
                : "text-on-surface-variant hover:bg-surface-container-high"
            }`}
          >
            <span className="material-symbols-outlined text-[20px]">settings</span>
            <span className="font-label-caps text-label-caps">Settings</span>
          </Link>
        </div>
      </aside>
    </>
  );
}
