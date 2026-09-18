"use client";

import { Send } from "lucide-react";
import { type KeyboardEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";

export function MessageComposer({
  onSend,
  disabled,
}: {
  onSend: (message: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex items-end gap-2 border-t border-border bg-card p-3">
      <Textarea
        aria-label="Message"
        rows={1}
        placeholder="Type your message… (Enter to send, Shift+Enter for a new line)"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className="max-h-32 min-h-10"
      />
      <Button onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message">
        <Send className="size-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
