// Decision 2 — application identity only, NOT authentication.
// First use: prompt for display_name, generate user_id client-side (uuid v4),
// persist both in localStorage so same browser/device keeps same identity.
// Sent wherever backend requires user_id (POST /repos, conversations, review).
// Supports local identity switching (NOT authentication).

import type { AggregatedOutput } from "../types/api";

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

export function resetActiveUserState(): void {
  const identity = loadIdentity();
  if (!identity) return;
  localStorage.removeItem(`reviewmind_active_conversation_v1_${identity.user_id}`);
  localStorage.removeItem(`reviewmind_active_repo_v1_${identity.user_id}`);
}

const LEGACY_PURGE_KEY = "reviewmind_legacy_purged_v1";

/**
 * Remove old unscoped localStorage keys from before identity-scoping was added.
 * Runs once per browser (sentinel key prevents re-running).
 */
export function purgeLegacyKeys(): void {
  if (localStorage.getItem(LEGACY_PURGE_KEY)) return;

  const legacyPatterns = [
    /^reviewmind_messages_v1_\d+$/,           // reviewmind_messages_v1_42
    /^reviewmind_tool_calls_v1_\d+$/,         // reviewmind_tool_calls_v1_42
    /^reviewmind_review_session_v1_\d+$/,     // reviewmind_review_session_v1_42
    /^reviewmind_pending_turn_v1_\d+$/,       // reviewmind_pending_turn_v1_42
    /^reviewmind_active_conversation_v1$/,    // old unscoped active conversation
    /^reviewmind_active_repo_v1$/,            // old unscoped active repo
  ];

  const keysToRemove: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && legacyPatterns.some((p) => p.test(key))) {
      keysToRemove.push(key);
    }
  }

  for (const key of keysToRemove) {
    localStorage.removeItem(key);
  }

  localStorage.setItem(LEGACY_PURGE_KEY, "true");
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
  resetActiveUserState();
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

export interface BackendToolCall {
  agent_name: string;
  tool_name: string;
  tool_input: string | null;
  tool_output: string | null;
  tool_latency_ms: number | null;
  tool_status: "success" | "error" | null;
  created_at: string | null;
}

export interface BackendFinding {
  severity: string;
  confidence: number;
  title: string;
  description: string;
  evidence: string[];
  recommendation: string;
}

export interface BackendAggregatedResult {
  agent_name: string;
  findings: BackendFinding[];
  parse_status: string;
}

export interface BackendMessage {
  role: "user" | "assistant";
  content: string;
  order_index?: number;
  created_at?: string | null;
  result?: BackendAggregatedResult | null;
  timestamp?: string | null;
  review_session_id?: number | null;
  request_type?: string | null;
  tool_calls?: BackendToolCall[];
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
 * Fetch interleaved user messages and assistant results for a conversation.
 */
export async function fetchBackendMessages(
  user_id: string,
  conversation_id: number,
): Promise<BackendMessage[]> {
  try {
    const response = await fetch(
      `/api/v1/accounts/conversations/${conversation_id}/messages?user_id=${encodeURIComponent(user_id)}`,
    );
    if (!response.ok) {
      throw new Error(`Failed to fetch messages: ${response.statusText}`);
    }
    const data = await response.json();
    return data.messages ?? [];
  } catch (error) {
    console.error("Failed to fetch backend messages:", error);
    return [];
  }
}

/**
 * Import an account from the backend.
 * Sets the active identity and syncs conversations/repos/messages to localStorage.
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
  resetActiveUserState();
  localStorage.setItem(KEY, JSON.stringify(identity));

  // 4. Add to accounts list
  addAccountToStorage(identity);

  // 5. Sync conversations from backend
  const { syncConversationsFromBackend } = await import("./conversationCache");
  const conversations = await syncConversationsFromBackend(user_id);

  // 6. Sync repos from backend
  const { syncReposFromBackend } = await import("../api/repos");
  await syncReposFromBackend(user_id);

  // 7. Sync messages for each conversation
  const { saveMessages } = await import("./conversationState");

  for (const conv of conversations) {
    const backendMessages = await fetchBackendMessages(user_id, conv.conversation_id);
    if (backendMessages.length === 0) continue;

    const { formatAnswer } = await import("../utils/formatAnswer");
    const chatMessages = backendMessages.map((bm, idx) => {
      if (bm.role === "user") {
        return {
          id: `restored-user-${conv.conversation_id}-${idx}`,
          role: "user" as const,
          content: bm.content,
          timestamp: bm.created_at ?? new Date().toISOString(),
        };
      }
      // Assistant message
      const result = bm.result
        ? { ...bm.result, parse_status: bm.result.parse_status as AggregatedOutput["parse_status"] }
        : undefined;
      return {
        id: `restored-assistant-${conv.conversation_id}-${bm.review_session_id ?? idx}`,
        role: "assistant" as const,
        content: result ? formatAnswer(result as AggregatedOutput) : bm.content,
        result: result as AggregatedOutput | undefined,
        timestamp: bm.timestamp ?? new Date().toISOString(),
      };
    });

    saveMessages(conv.conversation_id, chatMessages);
  }

  return identity;
}
