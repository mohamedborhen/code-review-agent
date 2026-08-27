import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  saveIdentity,
  loadAllAccounts,
  switchToAccountById,
  type Identity,
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
