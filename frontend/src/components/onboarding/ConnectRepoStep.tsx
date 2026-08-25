import { useState } from "react";
import { registerRepo, addRegisteredRepo, getRegisteredRepos } from "../../api/repos";
import { loadIdentity } from "../../state/identity";

interface ConnectRepoStepProps {
  onComplete: () => void;
}

export default function ConnectRepoStep({ onComplete }: ConnectRepoStepProps) {
  const [repoUrl, setRepoUrl] = useState("");
  const [githubPat, setGithubPat] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const repos = getRegisteredRepos();
  const identity = loadIdentity();

  function parseRepoId(url: string): string | null {
    const match = url.match(/github\.com\/([^/]+\/[^/]+?)(?:\.git)?$/);
    return match ? match[1] : null;
  }

  async function handleConnect() {
    const repoId = parseRepoId(repoUrl);
    if (!repoId) {
      setError("Enter a valid GitHub repository URL");
      return;
    }
    if (!identity) {
      setError("No identity found — please sign in first");
      return;
    }
    setSaving(true);
    setError("");
    try {
      // POST /api/v1/repos — register with credentials
      const response = await registerRepo({
        repo_url: repoUrl,
        repo_id: repoId,
        user_id: identity.user_id,
        github_pat: githubPat || undefined,
        webhook_secret: webhookSecret || undefined,
      });

      // Add to local registration cache (§4 — no GET /api/v1/repos exists)
      addRegisteredRepo({
        repo_id: response.repo_id,
        repo_url: repoUrl,
        registered_at: new Date().toISOString(),
        webhook_configured: false,
      });

      setRepoUrl("");
      setGithubPat("");
      setWebhookSecret("");
      onComplete();
    } catch (e) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Failed to register repository");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="bg-surface-container rounded-lg border border-outline-variant overflow-hidden relative">
      <div className="absolute top-0 left-0 w-1 h-full bg-primary-container" />
      <div className="p-lg border-b border-outline-variant flex items-center justify-between bg-surface-container-low">
        <div className="flex items-center gap-md">
          <div className="w-8 h-8 rounded-full bg-surface-container-high border border-outline flex items-center justify-center font-label-caps text-label-caps text-on-surface">
            1
          </div>
          <div>
            <h2 className="font-headline-sm text-headline-sm text-on-surface">
              Connect Repositories
            </h2>
            <p className="font-body-sm text-body-sm text-on-surface-variant">
              Enter your GitHub repository details.
            </p>
          </div>
        </div>
      </div>
      <div className="p-lg space-y-md">
        {/* Already registered repos — from local cache (§4) */}
        {repos.length > 0 && (
          <div className="space-y-sm">
            {repos.map((r) => (
              <div
                key={r.repo_id}
                className="flex items-center justify-between p-sm border border-outline-variant rounded bg-surface-container-low"
              >
                <div className="flex items-center gap-sm">
                  <span className="material-symbols-outlined text-outline">folder</span>
                  <span className="font-code-md text-code-md text-on-surface">{r.repo_id}</span>
                </div>
                <div className="flex items-center gap-sm">
                  <span className="font-label-caps text-label-caps text-primary-container">
                    Registered
                  </span>
                  <span className="material-symbols-outlined text-primary-container filled">
                    check_circle
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Registration form */}
        <div className="space-y-sm">
          <input
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="w-full bg-surface-dim border border-outline-variant rounded-md py-2 px-4 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-code-sm text-code-sm placeholder-outline-variant"
          />
          <input
            value={githubPat}
            onChange={(e) => setGithubPat(e.target.value)}
            type="password"
            placeholder="GitHub Personal Access Token (required for private repos)"
            className="w-full bg-surface-dim border border-outline-variant rounded-md py-2 px-4 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-code-sm text-code-sm placeholder-outline-variant"
          />
          <input
            value={webhookSecret}
            onChange={(e) => setWebhookSecret(e.target.value)}
            type="password"
            placeholder="Webhook secret (optional — server generates if omitted)"
            className="w-full bg-surface-dim border border-outline-variant rounded-md py-2 px-4 text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container font-code-sm text-code-sm placeholder-outline-variant"
          />
          {error && <p className="text-error font-body-sm text-body-sm">{error}</p>}
          <button
            onClick={handleConnect}
            disabled={!repoUrl.trim() || saving}
            className="bg-primary-container text-on-primary-container font-label-caps text-label-caps px-md py-sm rounded font-bold hover:bg-primary-fixed transition-colors disabled:opacity-50"
          >
            {saving ? "Connecting..." : "Connect Repository"}
          </button>
        </div>
      </div>
    </section>
  );
}
