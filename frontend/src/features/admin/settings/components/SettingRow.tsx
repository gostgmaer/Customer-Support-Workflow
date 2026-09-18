"use client";

import { Check, Pencil, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import type { SystemSetting } from "@/types/api";

import { useResetSetting, useUpdateSetting } from "../hooks";
import { SETTINGS_METADATA } from "../metadata";

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "unlimited";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export function SettingRow({ setting }: { setting: SystemSetting }) {
  const meta = SETTINGS_METADATA[setting.key];
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(displayValue(setting.value));
  const updateSetting = useUpdateSetting();
  const resetSetting = useResetSetting();

  if (!meta) return null;

  const parseDraft = (): unknown => {
    if (meta.type === "boolean") return draft === "true";
    if (meta.type === "enum") return draft;
    if (meta.type === "nullable-float") return draft.trim() === "" ? null : Number(draft);
    return Number(draft);
  };

  const save = () => {
    updateSetting.mutate(
      { key: setting.key, value: parseDraft() },
      { onSuccess: () => setEditing(false) }
    );
  };

  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="font-medium text-foreground">{meta.label}</p>
          <Badge variant={setting.source === "override" ? "accent" : "default"}>{setting.source}</Badge>
        </div>
        <p className="mt-0.5 text-sm text-muted-foreground">{meta.description}</p>

        {editing ? (
          <div className="mt-2 flex items-center gap-2">
            {meta.type === "boolean" ? (
              <select
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="h-9 rounded-md border border-input bg-card px-2 text-sm"
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : meta.type === "enum" ? (
              <select
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="h-9 rounded-md border border-input bg-card px-2 text-sm"
              >
                {meta.options?.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                type="number"
                step={meta.type === "int" ? 1 : "any"}
                min={meta.min}
                max={meta.max}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={meta.type === "nullable-float" ? "unlimited" : undefined}
                className="h-9 w-40"
              />
            )}
            <Button size="sm" onClick={save} isLoading={updateSetting.isPending} aria-label="Save">
              <Check className="size-3.5" aria-hidden="true" />
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} aria-label="Cancel">
              <X className="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        ) : (
          <p className="mt-2 font-mono text-sm text-foreground">{displayValue(setting.value)}</p>
        )}
      </div>

      {!editing && (
        <div className="flex shrink-0 gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setDraft(displayValue(setting.value));
              setEditing(true);
            }}
          >
            <Pencil className="size-3.5" aria-hidden="true" />
            Edit
          </Button>
          {setting.source === "override" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => resetSetting.mutate(setting.key)}
              isLoading={resetSetting.isPending}
            >
              <RotateCcw className="size-3.5" aria-hidden="true" />
              Reset
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
