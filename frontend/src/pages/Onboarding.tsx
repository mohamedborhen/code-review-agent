import { useNavigate } from "react-router-dom";
import ConnectRepoStep from "../components/onboarding/ConnectRepoStep";
import WebhookStep from "../components/onboarding/WebhookStep";
import JiraStatusCard from "../components/onboarding/JiraStatusCard";
import { getRegisteredRepos } from "../api/repos";

export default function Onboarding() {
  const navigate = useNavigate();
  const repo_id = getRegisteredRepos()[0]?.repo_id;

  return (
    <div className="min-h-screen flex flex-col font-body-md">
      {/* Navbar */}
      <header className="bg-surface border-b border-outline-variant h-16 flex items-center justify-between px-lg fixed top-0 w-full z-50">
        <div className="flex items-center gap-sm">
          <span className="material-symbols-outlined text-primary-container filled">terminal</span>
          <span className="font-headline-sm text-headline-sm font-black tracking-tighter text-on-surface">
            ReviewMind
          </span>
        </div>
        <div>
          <button
            onClick={() => navigate("/", { replace: true })}
            className="font-label-caps text-label-caps text-on-surface-variant hover:text-on-surface transition-colors px-md py-sm rounded hover:bg-surface-container"
          >
            Skip Onboarding
          </button>
        </div>
      </header>

      <main className="flex-1 mt-16 pt-xl px-gutter md:px-lg max-w-4xl mx-auto w-full">
        <div className="mb-xl text-center">
          <h1 className="font-headline-xl text-headline-xl text-on-surface mb-sm">
            Environment Setup
          </h1>
          <p className="font-body-md text-body-md text-on-surface-variant">
            Connect your toolchain to enable AI-powered code intelligence.
          </p>
        </div>

        <div className="space-y-xl pb-xl">
          <ConnectRepoStep onComplete={() => {}} />
          <WebhookStep />
          <JiraStatusCard repo_id={repo_id} />
        </div>

        <div className="flex justify-end pt-sm border-t border-outline-variant mt-xl">
          <button
            onClick={() => navigate("/", { replace: true })}
            className="bg-primary-container text-on-primary-container font-label-caps text-label-caps px-lg py-sm rounded font-bold hover:bg-primary-fixed transition-colors"
          >
            Complete Setup
          </button>
        </div>
      </main>
    </div>
  );
}
