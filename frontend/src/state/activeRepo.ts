// Active repo/branch selection state — persisted in localStorage.
import { useState, useCallback, useEffect } from "react";

const STORAGE_KEY = "reviewmind_active_repo_v1";

export interface ActiveRepoState {
  repo_id: string | null;
  branch: string | null;
  registering: boolean;
}

function loadActiveRepo(): ActiveRepoState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { repo_id: null, branch: null, registering: false };
    const parsed = JSON.parse(raw);
    return {
      repo_id: parsed.repo_id ?? null,
      branch: parsed.branch ?? null,
      registering: false,
    };
  } catch {
    return { repo_id: null, branch: null, registering: false };
  }
}

function saveActiveRepo(state: { repo_id: string | null; branch: string | null }): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ repo_id: state.repo_id, branch: state.branch }));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

export function useActiveRepo() {
  const [state, setState] = useState<ActiveRepoState>(loadActiveRepo);

  // Persist on change
  useEffect(() => {
    saveActiveRepo({ repo_id: state.repo_id, branch: state.branch });
  }, [state.repo_id, state.branch]);

  const selectRepo = useCallback((repo_id: string) => {
    setState((s) => ({ ...s, repo_id, branch: null }));
  }, []);

  const selectBranch = useCallback((branch: string) => {
    setState((s) => ({ ...s, branch }));
  }, []);

  const setRegistering = useCallback((v: boolean) => {
    setState((s) => ({ ...s, registering: v }));
  }, []);

  const reset = useCallback(() => {
    setState({ repo_id: null, branch: null, registering: false });
  }, []);

  return { ...state, selectRepo, selectBranch, setRegistering, reset };
}
