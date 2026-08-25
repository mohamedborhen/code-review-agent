import { useNavigate } from "react-router-dom";
import { useSidebar } from "../../state/sidebar";

interface TopBarProps {
  children?: React.ReactNode;
}

export default function TopBar({ children }: TopBarProps) {
  const navigate = useNavigate();
  const { toggle } = useSidebar();

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
        <div className="flex gap-2">
          <button className="text-on-surface-variant hover:text-primary-fixed-dim p-1">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button
            onClick={() => navigate("/settings")}
            className="text-on-surface-variant hover:text-primary-fixed-dim p-1"
          >
            <span className="material-symbols-outlined">settings</span>
          </button>
          <button className="text-on-surface-variant hover:text-primary-fixed-dim p-1">
            <span className="material-symbols-outlined">help</span>
          </button>
        </div>
      </div>
    </header>
  );
}
