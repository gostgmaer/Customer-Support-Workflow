"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { getErrorMessage } from "@/lib/api/get-error-message";
import type { IntegrationAuthType, IntegrationType } from "@/types/api";

import { useCreateIntegration } from "../hooks";
import { CUSTOM_AUTH_CREDENTIAL_FIELDS, INTEGRATION_TYPE_META } from "../metadata";

const TYPES: IntegrationType[] = ["jira", "woocommerce", "smtp", "custom", "mcp", "openapi"];
const ALL_AUTH_TYPES: IntegrationAuthType[] = ["api_key", "bearer", "basic", "none"];

export function CreateIntegrationDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [type, setType] = useState<IntegrationType>("jira");
  const [customAuthType, setCustomAuthType] = useState<IntegrationAuthType>("api_key");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});

  const createIntegration = useCreateIntegration();
  const meta = INTEGRATION_TYPE_META[type];
  const allowedAuthTypes = meta.allowedAuthTypes ?? ALL_AUTH_TYPES;
  const authType = meta.fixedAuthType ?? customAuthType;
  const credentialFields = meta.fixedAuthType
    ? meta.credentialFields
    : CUSTOM_AUTH_CREDENTIAL_FIELDS[customAuthType];

  const reset = () => {
    setName("");
    setBaseUrl("");
    setValues({});
    setType("jira");
    setCustomAuthType("api_key");
  };

  const close = () => {
    reset();
    onClose();
  };

  const setValue = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setValues((prev) => ({ ...prev, [key]: event.target.value }));

  const setCheckbox = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setValues((prev) => ({ ...prev, [key]: event.target.checked ? "true" : "" }));

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const credentials: Record<string, string> = {};
    for (const field of credentialFields) credentials[field.key] = values[field.key] ?? "";

    const config: Record<string, unknown> = {};
    for (const field of meta.configFields) {
      if (field.type === "checkbox") {
        if (values[field.key] !== "true") continue;
        // The backend's `role` config field is a string tag (matched
        // against "storefront"), not a boolean - the checkbox is just a
        // friendlier way to set that one specific value.
        config[field.key] = field.key === "role" ? "storefront" : true;
        continue;
      }
      const raw = values[field.key];
      if (!raw) continue;
      config[field.key] = field.key === "smtp_port" ? Number(raw) : raw;
    }

    createIntegration.mutate(
      { name, type, base_url: baseUrl, auth_type: authType, credentials, config },
      { onSuccess: close }
    );
  };

  return (
    <Dialog open={open} onClose={close} title="Connect an integration" className="max-w-lg">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {createIntegration.isError && <Alert variant="error">{getErrorMessage(createIntegration.error)}</Alert>}

        <div>
          <Label htmlFor="integration-name">Name</Label>
          <Input
            id="integration-name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Production JIRA"
          />
        </div>

        <div>
          <Label htmlFor="integration-type">Type</Label>
          <select
            id="integration-type"
            value={type}
            onChange={(e) => {
              const nextType = e.target.value as IntegrationType;
              const nextAllowed = INTEGRATION_TYPE_META[nextType].allowedAuthTypes ?? ALL_AUTH_TYPES;
              setType(nextType);
              setValues({});
              if (!nextAllowed.includes(customAuthType)) setCustomAuthType(nextAllowed[0]);
            }}
            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {INTEGRATION_TYPE_META[t].label}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-xs text-muted-foreground">{meta.description}</p>
        </div>

        <div>
          <Label htmlFor="integration-base-url">Base URL</Label>
          <Input
            id="integration-base-url"
            required
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={meta.baseUrlPlaceholder}
          />
        </div>

        {meta.fixedAuthType === null && (
          <div>
            <Label htmlFor="integration-auth-type">Auth type</Label>
            <select
              id="integration-auth-type"
              value={customAuthType}
              onChange={(e) => {
                setCustomAuthType(e.target.value as IntegrationAuthType);
                setValues({});
              }}
              className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {allowedAuthTypes.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
        )}

        {[...credentialFields, ...meta.configFields].map((field) =>
          field.type === "checkbox" ? (
            <label key={field.key} htmlFor={`integration-${field.key}`} className="flex items-center gap-2 text-sm">
              <input
                id={`integration-${field.key}`}
                type="checkbox"
                checked={values[field.key] === "true"}
                onChange={setCheckbox(field.key)}
                className="h-4 w-4 rounded border-input"
              />
              {field.label}
            </label>
          ) : (
            <div key={field.key}>
              <Label htmlFor={`integration-${field.key}`}>{field.label}</Label>
              <Input
                id={`integration-${field.key}`}
                type={field.type}
                required={field.required}
                value={values[field.key] ?? ""}
                onChange={setValue(field.key)}
                placeholder={field.placeholder}
              />
            </div>
          )
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" isLoading={createIntegration.isPending}>
            Connect
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
