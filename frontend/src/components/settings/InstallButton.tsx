// PWA Install ReviewMind button — conditional on browser support.
import { usePwaInstall } from "../../hooks/usePwaInstall";

interface InstallButtonProps {
  className?: string;
}

export default function InstallButton({ className = "" }: InstallButtonProps) {
  const { isInstallable, isInstalled, install } = usePwaInstall();

  if (isInstalled) {
    return (
      <div className={`flex items-center gap-2 text-on-surface-variant ${className}`}>
        <span className="material-symbols-outlined text-[18px] text-primary-container">check_circle</span>
        <span className="font-body-sm text-on-surface-variant">ReviewMind is installed</span>
      </div>
    );
  }

  if (!isInstallable) {
    return null;
  }

  return (
    <button
      onClick={install}
      className={`flex items-center gap-2 bg-primary-container text-on-primary-container hover:bg-primary-fixed px-4 py-2 rounded-lg font-label-caps text-label-caps transition-colors ${className}`}
    >
      <span className="material-symbols-outlined text-[18px]">download</span>
      Install ReviewMind
    </button>
  );
}
