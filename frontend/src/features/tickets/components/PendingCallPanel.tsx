"use client";

import { Cable } from "lucide-react";

import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";

interface PendingCall {
  integration_name: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export function PendingCallPanel({
  pendingCall,
  values,
  onChange,
  disabled,
}: {
  pendingCall: PendingCall;
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  disabled?: boolean;
}) {
  const keys = Object.keys(pendingCall.arguments);

  return (
    <div className="rounded-md border border-border p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Cable className="size-4 text-muted-foreground" aria-hidden="true" />
        Proposed call to {pendingCall.integration_name}: <code className="text-xs">{pendingCall.tool_name}</code>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Review the arguments below before approving - edit any field to change what actually runs.
      </p>
      {keys.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">This tool takes no arguments.</p>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {keys.map((key) => (
            <div key={key}>
              <Label htmlFor={`pending-call-arg-${key}`}>{key}</Label>
              <Input
                id={`pending-call-arg-${key}`}
                value={values[key] ?? ""}
                onChange={(e) => onChange(key, e.target.value)}
                disabled={disabled}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
