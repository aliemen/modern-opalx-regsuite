import type { ReactNode } from "react";
import { SshKeysSection } from "./settings/SshKeysSection";
import { ConnectionsSection } from "./settings/ConnectionsSection";
import { ApiKeysSection } from "./settings/ApiKeysSection";
import { PasswordSection } from "./settings/PasswordSection";
import { UsernameSection } from "./settings/UsernameSection";

function SettingsGroup({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-fg text-sm font-semibold uppercase tracking-wide">
          {title}
        </h2>
        <p className="text-muted text-sm mt-1">{description}</p>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

/**
 * Thin shell. Each section is a self-contained component under
 * `pages/settings/` with its own queries, mutations, and form state.
 * Adding a section here is a one-line job; keeping the shell tiny means the
 * underlying component files never drift past the ~500 line budget.
 */
export function SettingsPage() {
  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto flex flex-col gap-8">
      <div>
        <h1 className="text-fg text-2xl font-semibold">Settings</h1>
        <p className="text-muted text-sm mt-1">
          Manage account identity, credentials, access tokens, and execution
          targets.
        </p>
      </div>

      <SettingsGroup
        title="Account"
        description="Identity shown on historical runs and new submissions."
      >
        <UsernameSection />
      </SettingsGroup>

      <SettingsGroup
        title="Security"
        description="Session credentials for signing in to the dashboard."
      >
        <PasswordSection />
      </SettingsGroup>

      <SettingsGroup
        title="Access"
        description="Keys used by scripts and remote SSH execution."
      >
        <SshKeysSection />
        <ApiKeysSection />
      </SettingsGroup>

      <SettingsGroup
        title="Execution"
        description="Reusable connection profiles for local and remote runs."
      >
        <ConnectionsSection />
      </SettingsGroup>
    </div>
  );
}
