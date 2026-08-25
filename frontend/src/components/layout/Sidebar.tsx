import { Link, useLocation } from "react-router-dom";
import { useSidebar } from "../../state/sidebar";

interface SidebarProps {
  conversations?: { conversation_id: number; title: string; repo_id: string }[];
  onNewConversation?: () => void;
  onSelectConversation?: (id: number) => void;
}

export default function Sidebar({
  conversations = [],
  onNewConversation,
  onSelectConversation,
}: SidebarProps) {
  const location = useLocation();
  const isSettings = location.pathname === "/settings";
  const { isOpen, close } = useSidebar();

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

        {/* New Conversation CTA — outlined variant per chat.html */}
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
                onClick={() => {
                  onSelectConversation?.(c.conversation_id);
                  close();
                }}
                className="group px-4 py-2 rounded hover:bg-surface-container-high cursor-pointer transition-colors"
              >
                <p className="font-body-sm text-on-surface truncate">{c.title}</p>
                <span className="inline-block mt-1 px-1.5 py-0.5 bg-surface-container-highest text-[10px] font-label-caps rounded text-on-surface-variant">
                  {c.repo_id.split("/").pop()}
                </span>
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
          <Link
            to="/settings"
            onClick={close}
            className="flex items-center gap-3 px-4 py-2 text-on-surface-variant hover:bg-surface-container-high transition-colors duration-150 rounded"
          >
            <span className="material-symbols-outlined text-[20px]">account_circle</span>
            <span className="font-label-caps text-label-caps">Account</span>
          </Link>
        </div>
      </aside>
    </>
  );
}
