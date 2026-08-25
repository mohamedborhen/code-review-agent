import { useState } from "react";
import Sidebar from "../components/layout/Sidebar";
import TopBar from "../components/layout/TopBar";
import ConnectedRepos from "../components/settings/ConnectedRepos";
import AccountCard from "../components/settings/AccountCard";
import JiraStatusCard from "../components/onboarding/JiraStatusCard";
import { useConversationCache } from "../state/conversationCache";
import { useNavigate } from "react-router-dom";

export default function Settings() {
  const { conversations } = useConversationCache();
  const navigate = useNavigate();
  const [refreshKey, setRefreshKey] = useState(0);
  const [jiraConnected, setJiraConnected] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Frontend-only filter over rendered settings sections
  const sections = [
    { key: "repos", label: "Connected Repositories" },
    { key: "jira", label: "Atlassian Jira" },
    { key: "account", label: "Account" },
  ];
  const filtered = searchQuery
    ? sections.filter((s) =>
        s.label.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : sections;

  return (
    <div className="min-h-screen bg-background flex">
      <Sidebar conversations={conversations} />

      <TopBar />

      {/* Main content — full width on mobile, offset by sidebar on desktop */}
      <main className="md:ml-[280px] mt-16 p-4 md:p-lg w-full md:w-[calc(100%-280px)] h-[calc(100vh-64px)] overflow-y-auto bg-surface-dim">
        <div className="max-w-6xl mx-auto">
          {/* Header */}
          <div className="mb-margin">
            <h2 className="font-headline-xl text-headline-xl text-on-surface mb-2">
              Settings & Integrations
            </h2>
            <p className="font-body-md text-body-md text-on-surface-variant">
              Manage your repository connections, webhooks, and external services.
            </p>
          </div>

          {/* Search — frontend-only filter per §7.4 */}
          <div className="mb-6">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search settings..."
              className="w-full sm:w-64 bg-[#0D1117] border border-outline-variant rounded-md py-1.5 px-3 text-body-sm text-on-surface focus:outline-none focus:border-primary-container focus:ring-1 focus:ring-primary-container transition-all"
            />
          </div>

          {/* Bento Grid Layout */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            {/* Left Column */}
            <div className="xl:col-span-2 flex flex-col gap-6">
              {filtered.includes(sections[0]) && (
                <ConnectedRepos
                  onAddRepo={() => navigate("/onboarding")}
                  refreshKey={refreshKey}
                />
              )}
            </div>

            {/* Right Column */}
            <div className="flex flex-col gap-6">
              {filtered.includes(sections[2]) && <AccountCard />}

              {filtered.includes(sections[1]) && (
                <div className="bg-[#161B22] border border-[#30363D] rounded-xl p-6 relative overflow-hidden group hover:border-[#8B949E] transition-colors duration-300">
                  <div className="absolute top-0 left-0 w-1 h-full bg-[#0052CC]" />
                  {jiraConnected ? (
                    <div className="flex flex-col gap-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded bg-[#0052CC]/10 flex items-center justify-center">
                            <span className="material-symbols-outlined text-[#0052CC] text-[20px] filled">
                              task_alt
                            </span>
                          </div>
                          <div>
                            <h4 className="font-headline-sm text-headline-sm text-on-surface">
                              Atlassian Jira
                            </h4>
                            <p className="font-body-sm text-body-sm text-on-surface-variant">
                              Connected
                            </p>
                          </div>
                        </div>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-container/10 text-primary-container font-label-caps text-label-caps border border-primary-container/20">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary-container" /> Active
                        </span>
                      </div>
                      <div className="flex items-center gap-3 pt-2 border-t border-outline-variant">
                        <button
                          onClick={() => setJiraConnected(false)}
                          className="text-on-surface-variant hover:text-error font-label-caps text-label-caps transition-colors flex items-center gap-1"
                        >
                          <span className="material-symbols-outlined text-[16px]">link_off</span>
                          Remove credentials
                        </button>
                      </div>
                    </div>
                  ) : (
                    <JiraStatusCard
                      connected={false}
                      onConnect={() => setJiraConnected(true)}
                    />
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
