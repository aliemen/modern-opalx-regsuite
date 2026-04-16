import { SshKeysSection } from "./settings/SshKeysSection";
import { ConnectionsSection } from "./settings/ConnectionsSection";
import { ApiKeysSection } from "./settings/ApiKeysSection";

/**
 * Thin shell. Each section is a self-contained component under
 * `pages/settings/` with its own queries, mutations, and form state.
 * Adding a section here is a one-line job; keeping the shell tiny means the
 * underlying component files never drift past the ~500 line budget.
 */
export function SettingsPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto flex flex-col gap-6">
      <h1 className="text-fg text-2xl font-semibold">Settings</h1>
      <SshKeysSection />
      <ConnectionsSection />
      <ApiKeysSection />
    </div>
  );
}
