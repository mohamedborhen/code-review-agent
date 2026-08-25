import { useState, useRef, useEffect, useCallback } from "react";
import { getBranches } from "../../api/repos";
import type { Branch } from "../../types/api";

interface BranchDropdownProps {
  repoId: string | null;
  selectedBranch: string | null;
  onSelect: (branch: string) => void;
}

export default function BranchDropdown({ repoId, selectedBranch, onSelect }: BranchDropdownProps) {
  const [open, setOpen] = useState(false);
  const [manualEntry, setManualEntry] = useState(false);
  const [manualValue, setManualValue] = useState("");
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false); // true = degraded to manual entry
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fetchBranches = useCallback(async () => {
    if (!repoId) return;
    setLoading(true);
    setError(false);
    try {
      const response = await getBranches(repoId);
      // §2: response is WRAPPED — { repo_id, branches: [...] }
      setBranches(response.branches);
    } catch (err) {
      // Handle 404 (unregistered) and 500 (malformed GitHub payload)
      // §2/§6: degrade to manual branch-entry fallback
      console.warn("Failed to fetch branches, degraded to manual entry:", err);
      setBranches([]);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [repoId]);

  // Fetch branches when dropdown opens
  useEffect(() => {
    if (repoId && open) {
      fetchBranches();
    }
  }, [repoId, open, fetchBranches]);

  return (
    <div ref={ref} className="relative">
      {manualEntry ? (
        <div className="flex items-center gap-sm">
          <input
            autoFocus
            value={manualValue}
            onChange={(e) => setManualValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && manualValue.trim()) {
                onSelect(manualValue.trim());
                setManualEntry(false);
              }
              if (e.key === "Escape") setManualEntry(false);
            }}
            placeholder="Branch name"
            className="bg-surface-container px-3 py-1.5 rounded border border-outline-variant font-code-sm text-code-sm text-on-surface focus:outline-none focus:border-primary-fixed-dim w-48"
          />
          <button
            onClick={() => setManualEntry(false)}
            className="text-on-surface-variant hover:text-on-surface text-sm"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-sm bg-surface-container px-3 py-1.5 rounded border border-outline-variant hover:border-primary-fixed-dim transition-colors"
          disabled={!repoId}
        >
          <span className="material-symbols-outlined text-on-surface-variant text-[18px]">
            account_tree
          </span>
          <span className="font-code-sm text-code-sm text-on-surface">
            {selectedBranch ?? "Select branch"}
          </span>
          <span className="material-symbols-outlined text-on-surface-variant text-[16px]">
            arrow_drop_down
          </span>
        </button>
      )}

      {open && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-surface-container border border-outline-variant rounded-lg shadow-lg z-50 py-1 max-h-64 overflow-y-auto">
          {loading && (
            <div className="px-4 py-2 text-on-surface-variant font-body-sm text-body-sm flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px] animate-spin">progress_activity</span>
              Loading branches...
            </div>
          )}
          {!loading && error && (
            <div className="px-4 py-2 text-on-surface-variant font-body-sm text-body-sm">
              <p className="mb-2">Could not load branches</p>
              <button
                onClick={() => {
                  setOpen(false);
                  setManualEntry(true);
                }}
                className="text-primary-fixed-dim hover:underline text-sm"
              >
                Enter branch manually
              </button>
            </div>
          )}
          {!loading && !error && branches.length === 0 && (
            <div className="px-4 py-2 text-on-surface-variant font-body-sm text-body-sm">
              {repoId ? "No branches found" : "Select a repo first"}
            </div>
          )}
          {!loading && !error && branches.map((b) => (
            <button
              key={b.name}
              onClick={() => {
                onSelect(b.name);
                setOpen(false);
              }}
              className={`w-full text-left px-4 py-2 flex items-center gap-3 hover:bg-surface-container-high transition-colors ${
                b.name === selectedBranch ? "bg-surface-container-high" : ""
              }`}
            >
              <span className="material-symbols-outlined text-on-surface-variant text-[18px]">
                account_tree
              </span>
              <span className="font-code-sm text-code-sm text-on-surface">{b.name}</span>
            </button>
          ))}
          <div className="border-t border-outline-variant mt-1 pt-1">
            <button
              onClick={() => {
                setOpen(false);
                setManualEntry(true);
              }}
              className="w-full text-left px-4 py-2 flex items-center gap-3 hover:bg-surface-container-high transition-colors text-on-surface-variant"
            >
              <span className="material-symbols-outlined text-[18px]">edit</span>
              <span className="font-label-caps text-label-caps">Enter branch manually</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
