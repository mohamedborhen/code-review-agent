import React from "react";
import { getRegisteredRepos, removeRegisteredRepo } from "../../api/repos";

interface ConnectedReposProps {
  onAddRepo?: () => void;
  refreshKey?: number;
  setRefreshKey?: React.Dispatch<React.SetStateAction<number>>;
}

export default function ConnectedRepos({ onAddRepo, refreshKey, setRefreshKey }: ConnectedReposProps) {
  const repos = getRegisteredRepos();

  return (
    <div className="bg-[#161B22] border border-[#30363D] rounded-xl p-6 relative overflow-hidden group hover:border-[#8B949E] transition-colors duration-300">
      <div className="absolute top-0 left-0 w-1 h-full bg-primary-container" />
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary-container text-[24px]">
            source
          </span>
          <h3 className="font-headline-lg text-headline-lg text-on-surface">
            Connected Repositories
          </h3>
        </div>
        <button
          onClick={onAddRepo}
          className="bg-transparent border border-primary-container text-primary-container hover:bg-primary-container hover:text-[#0A0E12] font-label-caps text-label-caps py-1.5 px-3 rounded transition-colors flex items-center gap-2"
        >
          <span className="material-symbols-outlined text-[16px]">add</span> Add Repo
        </button>
      </div>
      <div className="space-y-3" key={refreshKey}>
        {repos.length === 0 && (
          <p className="font-body-sm text-on-surface-variant py-4 text-center">
            No repositories connected yet
          </p>
        )}
        {repos.map((repo) => (
          <div
            key={repo.repo_id}
            className="flex items-center justify-between p-3 rounded-lg bg-[#0D1117] border border-[#30363D] group/item hover:border-primary-container/50 transition-colors"
          >
            <div className="flex items-center gap-4">
              <span className="material-symbols-outlined text-on-surface-variant">folder</span>
              <div>
                <p className="font-code-md text-code-md text-on-surface font-semibold">
                  {repo.repo_id}
                </p>
                <div className="flex items-center gap-2 text-code-sm text-on-surface-variant">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      repo.webhook_configured ? "bg-primary-container" : "bg-outline"
                    }`}
                  />
                  {repo.webhook_configured ? "Webhook configured" : "Webhook not configured"}
                </div>
              </div>
            </div>
            <button
              onClick={() => {
                removeRegisteredRepo(repo.repo_id);
                setRefreshKey?.((k) => k + 1);
              }}
              className="text-on-surface-variant hover:text-error font-label-caps text-label-caps transition-colors flex items-center gap-1 opacity-0 group-hover/item:opacity-100"
            >
              <span className="material-symbols-outlined text-[16px]">delete</span>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
