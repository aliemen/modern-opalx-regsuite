import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Trash2, Key } from "lucide-react";
import { listSshKeys, uploadSshKey, deleteSshKey, SshKeyInfo } from "../api/keys";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [keyName, setKeyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { data: keys, isLoading } = useQuery<SshKeyInfo[]>({
    queryKey: ["ssh-keys"],
    queryFn: listSshKeys,
  });

  const uploadMut = useMutation({
    mutationFn: ({ name, file }: { name: string; file: File }) =>
      uploadSshKey(name, file),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["ssh-keys"] });
      setKeyName("");
      if (fileRef.current) fileRef.current.value = "";
      setError(null);
      setSuccess(`Key "${data.name}" uploaded.`);
    },
    onError: (e: unknown) => {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Upload failed.";
      setError(msg);
      setSuccess(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteSshKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ssh-keys"] });
      setSuccess(null);
    },
  });

  function handleUpload() {
    setError(null);
    setSuccess(null);
    const file = fileRef.current?.files?.[0];
    if (!keyName.trim()) {
      setError("Please enter a key name.");
      return;
    }
    if (!file) {
      setError("Please select a private key file.");
      return;
    }
    uploadMut.mutate({ name: keyName.trim(), file });
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-fg text-2xl font-semibold mb-6">Settings</h1>

      {/* SSH Keys section */}
      <div className="bg-surface border border-border rounded-xl p-6">
        <h2 className="text-fg text-lg font-medium mb-4 flex items-center gap-2">
          <Key size={18} />
          SSH Keys
        </h2>
        <p className="text-muted text-sm mb-5">
          Manage private keys used for remote execution. Keys are referenced by
          name in <code className="text-fg">config.toml</code> arch configs via{" "}
          <code className="text-fg">remote_key_name</code>.
        </p>

        {/* Upload form */}
        <div className="flex flex-col gap-3 mb-6">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Key name (e.g. gpu-key)"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            />
            <input
              ref={fileRef}
              type="file"
              accept=".pem,.key,.pub,.id_rsa,.id_ed25519,*"
              className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm file:mr-3 file:border-0 file:bg-transparent file:text-accent file:text-sm file:font-medium"
            />
          </div>
          <button
            onClick={handleUpload}
            disabled={uploadMut.isPending}
            className="flex items-center justify-center gap-2 bg-accent text-bg font-medium rounded-md py-2 text-sm hover:brightness-110 transition disabled:opacity-50 w-fit px-5"
          >
            <Upload size={15} />
            {uploadMut.isPending ? "Uploading..." : "Upload Key"}
          </button>
          {error && <p className="text-failed text-sm">{error}</p>}
          {success && <p className="text-passed text-sm">{success}</p>}
        </div>

        {/* Keys table */}
        {isLoading ? (
          <p className="text-muted text-sm">Loading keys...</p>
        ) : keys && keys.length > 0 ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-muted text-left">
                <th className="pb-2 font-medium">Name</th>
                <th className="pb-2 font-medium">Fingerprint</th>
                <th className="pb-2 font-medium">Added</th>
                <th className="pb-2 font-medium w-10"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr
                  key={k.name}
                  className="border-b border-border last:border-0"
                >
                  <td className="py-2.5 text-fg font-mono">{k.name}</td>
                  <td className="py-2.5 text-muted font-mono text-xs truncate max-w-[200px]">
                    {k.fingerprint ?? "-"}
                  </td>
                  <td className="py-2.5 text-muted">
                    {new Date(k.created_at).toLocaleDateString()}
                  </td>
                  <td className="py-2.5">
                    <button
                      onClick={() => deleteMut.mutate(k.name)}
                      disabled={deleteMut.isPending}
                      className="text-muted hover:text-failed transition p-1"
                      title={`Delete ${k.name}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-muted text-sm">
            No SSH keys registered. Upload a private key to enable remote
            execution.
          </p>
        )}
      </div>
    </div>
  );
}
