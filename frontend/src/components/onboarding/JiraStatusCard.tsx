import { useState } from "react";
import { validateJira, storeJiraCredentials } from "../../api/jira";
import { loadIdentity } from "../../state/identity";

interface JiraStatusCardProps {
  connected?: boolean;
  onConnect?: (url: string, email: string, token: string) => void;
  onDisconnect?: () => void;
}

export default function JiraStatusCard({
  connected = false,
  onConnect,
  onDisconnect,
}: JiraStatusCardProps) {
  const [jiraUrl, setJiraUrl] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  const identity = loadIdentity();

  async function handleTest() {
    if (!identity) {
      setError("No identity found — please sign in first");
      return;
    }
    setTesting(true);
    setError("");
    try {
      const body = {
        user_id: identity.user_id,
        jira_url: jiraUrl,
        jira_email: email,
        jira_api_token: token,
      };

      // POST /api/v1/integrations/jira/validate — probe, never stores
      const validation = await validateJira(body);

      if (!validation.ok) {
        setError(validation.error || "Connection test failed");
        return;
      }

      // On success, save credentials server-side
      await storeJiraCredentials(body);

      onConnect?.(jiraUrl, email, token);
    } catch (e) {
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("Connection failed");
      }
    } finally {
      setTesting(false);
    }
  }

  return (
    <section className="bg-surface-container rounded-lg border border-outline-variant overflow-hidden relative">
      <div className="p-lg">
        <div className="flex items-center justify-between mb-sm">
          <h2 className="font-headline-sm text-headline-sm text-on-surface">
            Issue Tracker Integration
          </h2>
        </div>
        <p className="font-body-sm text-body-sm text-on-surface-variant mb-md">
          Link Jira to automatically enrich code reviews with ticket context.
        </p>

        {connected ? (
          <div className="border border-outline-variant rounded-md bg-surface-dim p-md">
            <div className="flex items-center justify-between mb-md">
              <div className="flex items-center gap-md">
                <div className="w-8 h-8 flex items-center justify-center bg-[#0052CC] rounded-sm p-1">
                  <span className="material-symbols-outlined text-white text-[20px] filled">
                    task_alt
                  </span>
                </div>
                <div>
                  <div className="font-body-md text-on-surface">Atlassian Jira</div>
                  <div className="flex items-center gap-1 text-code-sm text-on-surface-variant">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary-container" />
                    Connected
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 pt-2 border-t border-outline-variant">
              <button
                onClick={onDisconnect}
                className="text-on-surface-variant hover:text-error font-label-caps text-label-caps transition-colors flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-[16px]">link_off</span>
                Remove credentials
              </button>
            </div>
          </div>
        ) : (
          <div className="border border-outline-variant rounded-md bg-surface-dim p-md space-y-sm">
            <input
              value={jiraUrl}
              onChange={(e) => setJiraUrl(e.target.value)}
              placeholder="https://your-team.atlassian.net"
              className="w-full bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container font-code-sm text-code-sm placeholder-outline-variant"
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Jira email"
              className="w-full bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container font-code-sm text-code-sm placeholder-outline-variant"
            />
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              placeholder="Jira API token"
              className="w-full bg-surface-container border border-outline-variant rounded py-2 px-3 text-on-surface focus:outline-none focus:border-primary-container font-code-sm text-code-sm placeholder-outline-variant"
            />
            {error && <p className="text-error font-body-sm text-body-sm">{error}</p>}
            <button
              onClick={handleTest}
              disabled={!jiraUrl || !email || !token || testing}
              className="w-full bg-primary-container text-on-primary-container font-label-caps text-label-caps py-2 px-4 rounded font-bold hover:bg-primary-fixed transition-colors disabled:opacity-50"
            >
              {testing ? "Testing..." : "Test Connection"}
            </button>
            <p className="text-[11px] text-on-surface-variant text-center">
              Credentials are stored encrypted server-side only
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
