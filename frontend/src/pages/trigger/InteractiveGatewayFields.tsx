import { ShieldAlert } from "lucide-react";
import type { Connection } from "../../api/connections";

interface InteractiveGatewayFieldsProps {
  connection: Connection;
  gatewayPassword: string;
  gatewayOtp: string;
  onGatewayPasswordChange: (value: string) => void;
  onGatewayOtpChange: (value: string) => void;
}

export function InteractiveGatewayFields({
  connection,
  gatewayPassword,
  gatewayOtp,
  onGatewayPasswordChange,
  onGatewayOtpChange,
}: InteractiveGatewayFieldsProps) {
  return (
    <div className="border border-border rounded-md p-4 flex flex-col gap-3 bg-bg">
      <div className="flex items-start gap-2 text-sm text-muted">
        <ShieldAlert size={16} className="mt-0.5 shrink-0 text-accent" />
        <p className="text-xs">
          This connection uses an interactive SSH gateway
          ({connection.gateway!.host}). Enter your password and Microsoft
          Authenticator OTP code below. Credentials are used for this run only
          and are never stored.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-xs text-muted mb-1">
            Gateway password
          </label>
          <input
            type="password"
            value={gatewayPassword}
            onChange={(e) => onGatewayPasswordChange(e.target.value)}
            placeholder="PSI password"
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            autoComplete="off"
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">
            Authenticator OTP
          </label>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={gatewayOtp}
            onChange={(e) => onGatewayOtpChange(e.target.value)}
            placeholder="6-digit code"
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-fg text-sm focus:outline-none focus:border-accent"
            autoComplete="off"
          />
        </div>
      </div>
      <p className="text-xs text-muted">
        Use the OTP code from Microsoft Authenticator (not the push
        notification). The code is time-limited - enter it just before clicking
        Start Run. If the target machine is busy, the run cannot be queued.
      </p>
    </div>
  );
}
