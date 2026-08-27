import { useNavigate } from "react-router-dom";
import { useSidebar } from "../../state/sidebar";
import { loadIdentity } from "../../state/identity";

interface TopBarProps {
  children?: React.ReactNode;
}

export default function TopBar({ children }: TopBarProps) {
  const navigate = useNavigate();
  const { toggle } = useSidebar();
  const identity = loadIdentity();

  return (
    <header className="fixed top-0 right-0 left-0 md:left-[280px] h-16 border-b border-outline-variant bg-surface flex items-center justify-between px-4 md:px-lg z-20">
      <div className="flex items-center gap-md">
        {/* Hamburger menu for mobile */}
        <button
          onClick={toggle}
          className="md:hidden text-on-surface-variant hover:text-primary-fixed-dim p-1"
          aria-label="Toggle menu"
        >
          <span className="material-symbols-outlined">menu</span>
        </button>

        <span className="font-headline-sm text-headline-sm font-black tracking-tighter text-on-surface hidden sm:block">
          ReviewMind
        </span>
        {children}
      </div>

      <div className="flex items-center gap-md">
        {/* Identity indicator — clickable, opens Settings */}
        {identity && (
          <button
            onClick={() => navigate("/settings")}
            className="flex items-center gap-2 hover:bg-surface-container-high rounded-lg px-2 py-1.5 transition-colors group"
            title="Open Settings"
          >
            {/* Small avatar */}
            <div className="w-7 h-7 rounded-full border border-primary-container/40 bg-surface-container-high flex items-center justify-center">
              <span className="material-symbols-outlined text-primary-container text-[16px]">
                person
              </span>
            </div>
            {/* Display name + truncated ID — hidden on small screens */}
            <div className="hidden sm:flex flex-col items-start">
              <span className="font-body-sm text-on-surface text-sm leading-tight">
                {identity.display_name}
              </span>
              <span className="font-code-xs text-on-surface-variant text-[10px] leading-tight opacity-70">
                {identity.user_id.slice(0, 8)}...
              </span>
            </div>
            {/* Settings icon */}
            <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary-fixed-dim text-[20px]">
              settings
            </span>
          </button>
        )}
      </div>
    </header>
  );
}
