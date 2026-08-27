import { useState } from "react";
import {
  loadIdentity,
  switchToAccountById,
  createNewAccount,
  type Identity,
} from "../../state/identity";

interface AccountCardProps {
  onAccountSwitch?: (identity: Identity, isNewAccount?: boolean) => void;
}

export default function AccountCard({ onAccountSwitch }: AccountCardProps) {
  const identity = loadIdentity();
  const [showSwitch, setShowSwitch] = useState(false);
  const [switchId, setSwitchId] = useState("");
  const [switchError, setSwitchError] = useState("");
  const [showNewAccount, setShowNewAccount] = useState(false);
  const [newName, setNewName] = useState("");
  const [justCreated, setJustCreated] = useState<Identity | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSwitch = () => {
    const id = switchId.trim();
    if (!id) return;
    setSwitchError("");
    const switched = switchToAccountById(id);
    if (switched) {
      onAccountSwitch?.(switched);
    } else {
      setSwitchError("No account with this ID found on this device. The account must have been created here first.");
    }
  };

  const handleCreateAccount = () => {
    if (!newName.trim()) return;
    const newIdentity = createNewAccount(newName.trim());
    setNewName("");
    setShowNewAccount(false);
    setJustCreated(newIdentity);
    onAccountSwitch?.(newIdentity, true);
  };

  const handleCopyId = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select text for manual copy
    }
  };

  return (
    <div className="bg-[#1C2128] border border-[#30363D] rounded-xl p-6 relative overflow-hidden group hover:border-[#8B949E] transition-colors duration-300 shadow-[0_0_15px_rgba(0,220,229,0.03)] hover:shadow-[0_0_20px_rgba(0,220,229,0.08)]">
      <div className="flex flex-col items-center text-center">
        <div className="w-20 h-20 rounded-full border-2 border-primary-container p-1 mb-4 relative">
          <div className="w-full h-full rounded-full bg-surface-container-high flex items-center justify-center">
            <span className="material-symbols-outlined text-primary-container text-[32px]">
              person
            </span>
          </div>
          <div className="absolute bottom-0 right-0 w-4 h-4 bg-[#161B22] rounded-full flex items-center justify-center">
            <div className="w-2.5 h-2.5 bg-primary-container rounded-full" />
          </div>
        </div>
        <h4 className="font-headline-sm text-headline-sm text-on-surface mb-1">
          {identity?.display_name ?? "User"}
        </h4>
        <div className="flex items-center gap-1.5 mb-1">
          <p className="font-code-sm text-code-sm text-on-surface-variant">
            ID: {identity?.user_id}
          </p>
          {identity && (
            <button
              onClick={() => handleCopyId(identity.user_id)}
              className="text-on-surface-variant hover:text-primary-container p-0.5 rounded transition-colors"
              title="Copy Account ID"
            >
              <span className="material-symbols-outlined text-[14px]">
                {copied ? "check" : "content_copy"}
              </span>
            </button>
          )}
        </div>
        <p className="font-body-xs text-on-surface-variant opacity-60">
          Application identity only — not authentication
        </p>
      </div>

      {/* Just created — show the new Account ID prominently */}
      {justCreated && (
        <div className="mt-4 pt-4 border-t border-[#30363D]">
          <div className="bg-primary-container/10 border border-primary-container/30 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="material-symbols-outlined text-primary-container text-[18px]">
                key
              </span>
              <p className="font-label-sm text-label-sm text-primary-container">
                Save your Account ID
              </p>
            </div>
            <p className="font-body-xs text-on-surface-variant mb-3">
              Copy and store this ID. You will need it to switch back to this account.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-surface-container border border-outline-variant rounded px-3 py-2 font-code-sm text-on-surface text-sm break-all">
                {justCreated.user_id}
              </code>
              <button
                onClick={() => handleCopyId(justCreated.user_id)}
                className="shrink-0 bg-primary-container text-on-primary-container px-3 py-2 rounded text-sm font-medium hover:bg-primary-fixed transition-colors flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-[16px]">
                  {copied ? "check" : "content_copy"}
                </span>
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <button
              onClick={() => setJustCreated(null)}
              className="mt-2 text-on-surface-variant hover:text-on-surface text-xs"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Switch Account */}
      <div className="mt-4 pt-4 border-t border-[#30363D]">
        {!showSwitch ? (
          <button
            onClick={() => {
              setShowSwitch(true);
              setShowNewAccount(false);
            }}
            className="w-full flex items-center justify-center gap-2 bg-surface-container hover:bg-surface-container-high border border-outline-variant rounded-lg px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">swap_horiz</span>
            Switch Account
          </button>
        ) : (
          <div>
            <label className="font-label-sm text-label-sm text-on-surface-variant mb-2 block">
              Enter Account ID
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={switchId}
                onChange={(e) => {
                  setSwitchId(e.target.value);
                  setSwitchError("");
                }}
                placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
                className="flex-1 bg-surface-container border border-outline-variant rounded px-3 py-2 text-sm text-on-surface font-code-sm focus:outline-none focus:border-primary-container"
                onKeyDown={(e) => e.key === "Enter" && handleSwitch()}
              />
              <button
                onClick={handleSwitch}
                disabled={!switchId.trim()}
                className="bg-primary-container text-on-primary-container px-3 py-2 rounded text-sm font-medium disabled:opacity-50"
              >
                Switch
              </button>
              <button
                onClick={() => {
                  setShowSwitch(false);
                  setSwitchId("");
                  setSwitchError("");
                }}
                className="text-on-surface-variant hover:text-on-surface px-2 py-2 rounded text-sm"
              >
                Cancel
              </button>
            </div>
            {switchError && (
              <p className="mt-2 text-xs text-error">{switchError}</p>
            )}
          </div>
        )}
      </div>

      {/* Create New Account */}
      <div className="mt-3">
        {showNewAccount ? (
          <div className="flex gap-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Display name for new account"
              className="flex-1 bg-surface-container border border-outline-variant rounded px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-primary-container"
              onKeyDown={(e) => e.key === "Enter" && handleCreateAccount()}
            />
            <button
              onClick={handleCreateAccount}
              disabled={!newName.trim()}
              className="bg-primary-container text-on-primary-container px-3 py-2 rounded text-sm font-medium disabled:opacity-50"
            >
              Create
            </button>
            <button
              onClick={() => {
                setShowNewAccount(false);
                setNewName("");
              }}
              className="text-on-surface-variant hover:text-on-surface px-2 py-2 rounded text-sm"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => {
              setShowNewAccount(true);
              setShowSwitch(false);
            }}
            className="w-full flex items-center justify-center gap-2 text-on-surface-variant hover:text-on-surface text-sm py-2 rounded transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">add</span>
            Create New Account
          </button>
        )}
      </div>
    </div>
  );
}
