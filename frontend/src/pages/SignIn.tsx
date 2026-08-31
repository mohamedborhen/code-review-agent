import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  saveIdentity,
  loadAllAccounts,
  switchToAccountById,
  lookupAccount,
  importAccountFromBackend,
  type Identity,
  type AccountLookupResult,
} from "../state/identity";


interface SignInProps {
  onIdentityCreated: (identity: Identity) => void;
}

interface AccountEntry {
  user_id: string;
  display_name: string;
  created_at: string;
  last_used: string;
}

export default function SignIn({ onIdentityCreated }: SignInProps) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [accounts, setAccounts] = useState<AccountEntry[]>([]);
  const navigate = useNavigate();

  // Account restore state
  const [restoreUserId, setRestoreUserId] = useState("");
  const [restoreDisplayName, setRestoreDisplayName] = useState("");
  const [isLookingUp, setIsLookingUp] = useState(false);
  const [lookupResult, setLookupResult] = useState<AccountLookupResult | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [isRestoring, setIsRestoring] = useState(false);

  useEffect(() => {
    setAccounts(loadAllAccounts());
  }, []);

  function handleContinue() {
    if (!name.trim()) {
      setError("Display name is required");
      return;
    }
    const identity = saveIdentity(name.trim());
    onIdentityCreated(identity);
    navigate("/onboarding", { replace: true });
  }

  function handleSwitchAccount(user_id: string) {
    const identity = switchToAccountById(user_id);
    if (identity) {
      onIdentityCreated(identity);
      navigate("/", { replace: true });
    }
  }

  async function handleLookupAccount() {
    if (!restoreUserId.trim()) {
      setLookupError("Please enter an Account ID");
      return;
    }

    setIsLookingUp(true);
    setLookupError("");
    setLookupResult(null);

    try {
      const result = await lookupAccount(restoreUserId.trim());
      if (result) {
        setLookupResult(result);
      } else {
        setLookupError("Account not found. Check the ID and try again.");
      }
    } catch {
      setLookupError("Failed to look up account. Is the backend running?");
    } finally {
      setIsLookingUp(false);
    }
  }

  async function handleRestoreAccount() {
    if (!lookupResult || !restoreDisplayName.trim()) {
      setLookupError("Please enter a display name for this account");
      return;
    }

    setIsRestoring(true);
    setLookupError("");

    try {
      // Import the account with the provided display name
      const identity = await importAccountFromBackend(
        lookupResult.user_id,
        restoreDisplayName.trim()
      );

      if (identity) {
        onIdentityCreated(identity);
        navigate("/", { replace: true });
      } else {
        setLookupError("Failed to restore account. Please try again.");
      }
    } catch {
      setLookupError("Failed to restore account. Please try again.");
    } finally {
      setIsRestoring(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-gutter">
      <main className="w-full max-w-sm flex flex-col gap-margin relative">
        <div className="absolute -top-12 -left-12 w-32 h-32 bg-primary-fixed-dim/5 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-12 -right-12 w-32 h-32 bg-primary-fixed-dim/5 rounded-full blur-3xl pointer-events-none" />
        <div className="bg-surface border border-outline-variant rounded-lg p-margin flex flex-col gap-margin shadow-2xl relative z-10">
          <div className="flex flex-col items-center text-center gap-sm">
            <div className="w-12 h-12 rounded-lg bg-surface-container-high border border-outline-variant flex items-center justify-center mb-2">
              <span className="material-symbols-outlined text-primary-fixed-dim filled">
                terminal
              </span>
            </div>
            <h1 className="font-headline-lg text-headline-lg text-on-surface flex items-center gap-2">
              <span className="font-code-md text-code-md text-primary-fixed-dim">~/</span>
              ReviewMind
            </h1>
            <p className="font-body-sm text-body-sm text-on-surface-variant">
              Set up your application identity to begin.
            </p>
          </div>

          <div className="flex flex-col gap-md">
            {accounts.length > 0 && (
              <div className="flex flex-col gap-sm">
                <p className="font-label-caps text-label-caps text-on-surface-variant">
                  Existing Accounts
                </p>
                {accounts.map((acct) => (
                  <button
                    key={acct.user_id}
                    onClick={() => handleSwitchAccount(acct.user_id)}
                    className="w-full flex items-center gap-3 p-3 bg-surface-container hover:bg-surface-container-high border border-outline-variant rounded transition-colors duration-150 text-left"
                  >
                    <div className="w-9 h-9 rounded-full bg-surface-container-high border border-outline-variant flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-on-surface-variant text-[18px]">
                        person
                      </span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-body-md text-body-md text-on-surface truncate">
                        {acct.display_name}
                      </span>
                      <span className="font-code-xs text-code-xs text-on-surface-variant truncate">
                        {acct.user_id.slice(0, 8)}...{acct.user_id.slice(-4)}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {accounts.length > 0 && (
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-outline-variant" />
                <span className="font-body-xs text-body-xs text-on-surface-variant">or restore account</span>
                <div className="flex-1 h-px bg-outline-variant" />
              </div>
            )}

            {/* Account Restore Section */}
            <div className="flex flex-col gap-sm p-3 bg-surface-container-lowest border border-outline-variant/50 rounded">
              <p className="font-label-caps text-label-caps text-on-surface-variant">
                Restore Existing Account
              </p>
              <p className="font-body-xs text-body-xs text-on-surface-variant">
                Enter your Account ID (UUID) to restore from another browser or session.
              </p>

              <div className="flex gap-2">
                <input
                  value={restoreUserId}
                  onChange={(e) => {
                    setRestoreUserId(e.target.value);
                    setLookupError("");
                    setLookupResult(null);
                  }}
                  placeholder="Paste your Account ID (UUID)"
                  className="flex-1 bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-body-sm text-body-sm placeholder-outline-variant"
                  disabled={isLookingUp || isRestoring}
                />
                <button
                  onClick={handleLookupAccount}
                  disabled={isLookingUp || isRestoring || !restoreUserId.trim()}
                  className="px-4 py-2 bg-surface-container hover:bg-surface-container-high border border-outline-variant rounded transition-colors duration-150 font-body-sm text-body-sm text-on-surface disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLookingUp ? "Looking up..." : "Lookup"}
                </button>
              </div>

              {lookupError && (
                <p className="text-error font-body-sm text-body-sm">{lookupError}</p>
              )}

              {lookupResult && (
                <div className="flex flex-col gap-sm mt-2 p-3 bg-surface-container rounded border border-outline-variant">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-success text-[16px]">check_circle</span>
                    <span className="font-body-sm text-body-sm text-on-surface">
                      Account found
                    </span>
                  </div>
                  <div className="flex flex-col gap-1 text-body-xs text-on-surface-variant">
                    <span>{lookupResult.conversation_count} conversations</span>
                    <span>{lookupResult.repo_count} repositories</span>
                    <span>{lookupResult.review_count} reviews</span>
                  </div>

                  <div className="mt-2">
                    <label className="font-label-caps text-label-caps text-on-surface-variant mb-1 block">
                      Display Name (required)
                    </label>
                    <input
                      value={restoreDisplayName}
                      onChange={(e) => setRestoreDisplayName(e.target.value)}
                      placeholder="Enter a name for this account"
                      className="w-full bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-body-sm text-body-sm placeholder-outline-variant"
                      disabled={isRestoring}
                    />
                  </div>

                  <button
                    onClick={handleRestoreAccount}
                    disabled={isRestoring || !restoreDisplayName.trim()}
                    className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-primary-container text-on-primary-container hover:bg-primary-fixed border border-outline-variant rounded transition-colors duration-150 font-body-sm text-body-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isRestoring ? (
                      <>
                        <span className="material-symbols-outlined animate-spin text-[16px]">refresh</span>
                        Restoring...
                      </>
                    ) : (
                      <>
                        <span className="material-symbols-outlined text-[16px]">download</span>
                        Restore Account
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>

            {accounts.length > 0 && (
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-outline-variant" />
                <span className="font-body-xs text-body-xs text-on-surface-variant">or create new</span>
                <div className="flex-1 h-px bg-outline-variant" />
              </div>
            )}

            <div>
              <label className="font-label-caps text-label-caps text-on-surface-variant mb-1 block">
                Display Name
              </label>
              <input
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setError("");
                }}
                onKeyDown={(e) => e.key === "Enter" && handleContinue()}
                placeholder="Your name"
                className="w-full bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-body-md text-body-md placeholder-outline-variant"
                autoFocus
              />
            </div>

            {error && <p className="text-error font-body-sm text-body-sm">{error}</p>}

            <button
              onClick={handleContinue}
              className="w-full flex items-center justify-center gap-3 py-3 px-4 bg-surface-container hover:bg-surface-container-highest border border-outline-variant rounded transition-colors duration-150"
            >
              <span className="font-body-md text-body-md text-on-surface font-medium">
                Continue
              </span>
            </button>

            <div className="flex items-start gap-3 p-3 rounded bg-surface-container-lowest border border-outline-variant/50">
              <span className="material-symbols-outlined text-outline text-[16px] mt-0.5">
                info
              </span>
              <div className="flex flex-col">
                <span className="font-label-caps text-label-caps text-on-surface">
                  Application Identity Only
                </span>
                <span className="font-body-sm text-body-sm text-on-surface-variant">
                  This creates a local identity for the application. No authentication is performed.
                </span>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
