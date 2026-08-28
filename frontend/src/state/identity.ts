// Decision 2 — application identity only, NOT authentication.
// First use: prompt for display_name, generate user_id client-side (uuid v4),
// persist both in localStorage so same browser/device keeps same identity.
// Sent wherever backend requires user_id (POST /repos, conversations, review).
// Supports local identity switching (NOT authentication).

const KEY = "reviewmind_identity_v1";
const ACCOUNTS_KEY = "reviewmind_accounts_v1";

export interface Identity {
  user_id: string;
  display_name: string;
  created_at: string;
}

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function loadIdentity(): Identity | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Identity;
    if (!parsed.user_id || !parsed.display_name) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveIdentity(display_name: string, user_id?: string): Identity {
  const identity: Identity = {
    user_id: user_id ?? uuid(),
    display_name: display_name.trim(),
    created_at: new Date().toISOString(),
  };
  localStorage.setItem(KEY, JSON.stringify(identity));
  addAccountToStorage(identity);
  return identity;
}

export function ensureIdentity(display_namePrompt: () => string | null): Identity {
  const existing = loadIdentity();
  if (existing) return existing;
  const name = display_namePrompt();
  if (!name || !name.trim()) throw new Error("Display name is required");
  return saveIdentity(name);
}

export function clearIdentity(): void {
  localStorage.removeItem(KEY);
}

// --- Account switching (local, NOT authentication) ---

interface AccountEntry {
  user_id: string;
  display_name: string;
  created_at: string;
  last_used: string;
}

export function loadAllAccounts(): AccountEntry[] {
  try {
    const raw = localStorage.getItem(ACCOUNTS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveAccounts(accounts: AccountEntry[]): void {
  localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
}

function addAccountToStorage(identity: Identity): void {
  const accounts = loadAllAccounts();
  const existing = accounts.find((a) => a.user_id === identity.user_id);
  if (existing) {
    existing.last_used = new Date().toISOString();
  } else {
    accounts.push({
      ...identity,
      last_used: new Date().toISOString(),
    });
  }
  saveAccounts(accounts);
}

export function getAccountDisplayName(user_id: string): string | null {
  const accounts = loadAllAccounts();
  const account = accounts.find((a) => a.user_id === user_id);
  return account?.display_name ?? null;
}

export function switchToAccountById(user_id: string): Identity | null {
  const accounts = loadAllAccounts();
  const account = accounts.find((a) => a.user_id === user_id);
  if (!account) return null;
  account.last_used = new Date().toISOString();
  saveAccounts(accounts);
  const identity: Identity = {
    user_id: account.user_id,
    display_name: account.display_name,
    created_at: account.created_at,
  };
  localStorage.setItem(KEY, JSON.stringify(identity));
  return identity;
}

export function createNewAccount(display_name: string): Identity {
  const identity: Identity = {
    user_id: uuid(),
    display_name: display_name.trim(),
    created_at: new Date().toISOString(),
  };
  localStorage.setItem(KEY, JSON.stringify(identity));
  addAccountToStorage(identity);
  return identity;
}

// --- Account restore from backend (Phase 5, Decision 7 vault exception) ---

export interface AccountLookupResult {
  exists: boolean;
  user_id: string;
  display_name: string | null;
  conversation_count: number;
  repo_count: number;
  review_count: number;
}

export interface BackendConversation {
  conversation_id: number;
  repo_id: string;
  created_at: string | null;
  message_count: number;
  latest_review_id: number | null;
  latest_review_status: string | null;
}

export interface BackendRepo {
  repo_id: string;
  created_at: string | null;
  has_github_pat: boolean;
  has_webhook_secret: boolean;
  has_jira_token: boolean;
}

export interface BackendReview {
  review_session_id: number;
  conversation_id: number | null;
  repo_id: string;
  request_type: string;
  status: string | null;
  created_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  finding_count: number;
}

/**
 * Lookup an account by user_id to verify it exists in the backend.
 * Returns metadata about the account if it exists, null if not found.
 */
export async function lookupAccount(user_id: string): Promise<AccountLookupResult | null> {
  try {
    const response = await fetch(`/api/v1/accounts/lookup?user_id=${encodeURIComponent(user_id)}`);
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Lookup failed: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    console.error("Account lookup failed:", error);
    return null;
  }
}

/**
 * Fetch conversations from backend for a user.
 */
export async function fetchBackendConversations(user_id: string): Promise<BackendConversation[]> {
  try {
    const response = await fetch(`/api/v1/accounts/conversations?user_id=${encodeURIComponent(user_id)}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch conversations: ${response.statusText}`);
    }
    const data = await response.json();
    return data.conversations ?? [];
  } catch (error) {
    console.error("Failed to fetch backend conversations:", error);
    return [];
  }
}

/**
 * Fetch repos from backend for a user.
 */
export async function fetchBackendRepos(user_id: string): Promise<BackendRepo[]> {
  try {
    const response = await fetch(`/api/v1/accounts/repos?user_id=${encodeURIComponent(user_id)}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch repos: ${response.statusText}`);
    }
    const data = await response.json();
    return data.repos ?? [];
  } catch (error) {
    console.error("Failed to fetch backend repos:", error);
    return [];
  }
}

/**
 * Fetch reviews from backend for a user.
 */
export async function fetchBackendReviews(user_id: string): Promise<BackendReview[]> {
  try {
    const response = await fetch(`/api/v1/accounts/reviews?user_id=${encodeURIComponent(user_id)}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch reviews: ${response.statusText}`);
    }
    const data = await response.json();
    return data.reviews ?? [];
  } catch (error) {
    console.error("Failed to fetch backend reviews:", error);
    return [];
  }
}

/**
 * Import an account from the backend.
 * Sets the active identity and syncs conversations/repos to localStorage.
 * Returns the imported Identity, or null on failure.
 */
export async function importAccountFromBackend(
  user_id: string,
  display_name: string,
): Promise<Identity | null> {
  // 1. Verify account exists
  const lookup = await lookupAccount(user_id);
  if (!lookup || !lookup.exists) {
    return null;
  }

  // 2. Create identity with provided display name
  const identity: Identity = {
    user_id: user_id,
    display_name: display_name.trim(),
    created_at: new Date().toISOString(),
  };

  // 3. Save as active identity
  localStorage.setItem(KEY, JSON.stringify(identity));

  // 4. Add to accounts list
  addAccountToStorage(identity);

  return identity;
}
