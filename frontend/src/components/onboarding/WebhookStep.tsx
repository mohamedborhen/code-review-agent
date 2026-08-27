export default function WebhookStep() {
  return (
    <section className="bg-surface-container rounded-lg border border-outline-variant overflow-hidden relative opacity-75 hover:opacity-100 transition-opacity">
      <div className="p-lg flex flex-col md:flex-row md:items-center justify-between gap-md">
        <div className="flex items-start gap-md">
          <div className="w-8 h-8 rounded-full bg-surface-container-high border border-outline-variant flex items-center justify-center font-label-caps text-label-caps text-on-surface-variant mt-1">
            2
          </div>
          <div>
            <h2 className="font-headline-sm text-headline-sm text-on-surface flex items-center gap-sm">
              CI/CD Webhooks
              <span className="px-2 py-0.5 rounded-full bg-surface-variant text-on-surface-variant font-label-caps text-label-caps border border-outline-variant">
                Optional
              </span>
            </h2>
            <p className="font-body-sm text-body-sm text-on-surface-variant mt-xs">
              Trigger analysis automatically on pull requests.
            </p>

            {/* Static webhook instructions — fabricated URL §7.4 CUT */}
            <div className="mt-md p-sm bg-surface-dim border border-outline-variant rounded font-code-sm text-code-sm text-on-surface-variant">
              <p className="mb-2 font-semibold text-on-surface">Manual Webhook Setup</p>
              <ol className="list-decimal list-inside space-y-1 text-on-surface-variant">
                <li>Go to your repository Settings → Webhooks</li>
                <li>
                  Set Payload URL to{" "}
                  <code className="text-primary-fixed-dim">
                    {"<your-origin>"}/api/v1/webhook
                  </code>
                </li>
                <li>Set Content type to application/json</li>
                <li>
                  Enter the webhook secret you provided during registration
                </li>
                <li>Select "Just the push event"</li>
              </ol>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
