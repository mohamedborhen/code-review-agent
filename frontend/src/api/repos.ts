import { apiFetch } from "./client";
import type { BranchesResponse, RepoRegistrationRequest, RepoRegistrationResponse } from "../types/api";

// Local registration cache — IndexedDB or in-memory fallback.
// Mirrors successful POST /api/v1/repos calls.
// No GET /api/v1/repos exists (§3) — both lists render from this cache.
export interface RegisteredRepo {
  repo_id: string;
  repo_url: string;
  display_name?: string;
  registered_at: string;
  webhook_configured: boolean;
}

const STORAGE_KEY = "reviewmind_repos_v1";

function loadRepos(): RegisteredRepo[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRepos(repos: RegisteredRepo[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(repos));
}

export function getRegisteredRepos(): RegisteredRepo[] {
  return loadRepos();
}

export function addRegisteredRepo(repo: RegisteredRepo): void {
  const repos = loadRepos();
  if (!repos.find((r) => r.repo_id === repo.repo_id)) {
    repos.push(repo);
    saveRepos(repos);
  }
}

export function removeRegisteredRepo(repo_id: string): void {
  saveRepos(loadRepos().filter((r) => r.repo_id !== repo_id));
}

// POST /api/v1/repos — register a repository with credentials
// §2: response is { status: "accepted", repo_id, credential_stored }
export async function registerRepo(
  req: RepoRegistrationRequest,
): Promise<RepoRegistrationResponse> {
  return apiFetch<RepoRegistrationResponse>("/repos", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// GET /api/v1/repos/{repo_id:path}/branches — WRAPPED response
// §2: response is { repo_id, branches: [{name, sha, protected}] }
// Handle 404 (unregistered) AND 500 (malformed GitHub payload) — degrade to manual entry
export async function getBranches(
  repoId: string,
): Promise<BranchesResponse> {
  return apiFetch<BranchesResponse>(`/repos/${encodeURIComponent(repoId)}/branches`);
}
