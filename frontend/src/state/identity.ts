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
