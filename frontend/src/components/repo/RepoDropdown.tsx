import { useState, useRef, useEffect } from "react";
import { getRegisteredRepos } from "../../api/repos";

interface RepoDropdownProps {
  selectedRepoId: string | null;
  onSelect: (repoId: string) => void;
}

export default function RepoDropdown({ selectedRepoId, onSelect }: RepoDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const repos = getRegisteredRepos();

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selected = repos.find((r) => r.repo_id === selectedRepoId);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-sm bg-surface-container px-3 py-1.5 rounded border border-outline-variant hover:border-primary-fixed-dim transition-colors"
      >
        <span className="material-symbols-outlined text-on-surface-variant text-[18px]">folder</span>
        <span className="font-code-sm text-code-sm text-on-surface">
          {selected?.repo_id ?? "Select repo"}
        </span>
        <span className="material-symbols-outlined text-on-surface-variant text-[16px]">
          arrow_drop_down
        </span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-surface-container border border-outline-variant rounded-lg shadow-lg z-50 py-1">
          {repos.length === 0 && (
            <div className="px-4 py-3 text-on-surface-variant font-body-sm text-body-sm">
              No repos registered
            </div>
          )}
          {repos.map((repo) => (
            <button
              key={repo.repo_id}
              onClick={() => {
                onSelect(repo.repo_id);
                setOpen(false);
              }}
              className={`w-full text-left px-4 py-2 flex items-center gap-3 hover:bg-surface-container-high transition-colors ${
                repo.repo_id === selectedRepoId ? "bg-surface-container-high" : ""
              }`}
            >
              <span className="material-symbols-outlined text-on-surface-variant text-[18px]">
                folder
              </span>
              <span className="font-code-sm text-code-sm text-on-surface">{repo.repo_id}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
