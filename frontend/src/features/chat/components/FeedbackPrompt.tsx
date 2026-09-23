"use client";

import { Star, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { toast } from "@/store/toast-store";

import { useSubmitFeedback } from "../hooks";

/**
 * Phase 15 - CSAT. Shown when a `ticket_decision` push carries
 * `prompt_csat: true` (see useConversationSocket) - i.e. the conversation
 * just reached a genuine terminal state. Deliberately simple: a 1-5 star
 * rating plus an optional comment, not a full NPS-style survey.
 */
export function FeedbackPrompt({ conversationId, onDone }: { conversationId: string; onDone: () => void }) {
  const [rating, setRating] = useState(0);
  const [hovered, setHovered] = useState(0);
  const [comment, setComment] = useState("");
  const submitFeedback = useSubmitFeedback(conversationId);

  const handleSubmit = () => {
    if (rating === 0) return;
    submitFeedback.mutate(
      { rating, comment },
      {
        onSuccess: () => {
          toast.success("Thanks for the feedback!");
          onDone();
        },
      }
    );
  };

  return (
    <div className="flex flex-col gap-3 border-t border-border bg-secondary/40 px-4 py-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-foreground">How did we do?</p>
        <button
          type="button"
          onClick={onDone}
          aria-label="Dismiss feedback prompt"
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex items-center gap-1" role="radiogroup" aria-label="Rating from 1 to 5">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={rating === value}
            aria-label={`${value} star${value === 1 ? "" : "s"}`}
            onClick={() => setRating(value)}
            onMouseEnter={() => setHovered(value)}
            onMouseLeave={() => setHovered(0)}
          >
            <Star
              className="size-6 transition-colors"
              fill={(hovered || rating) >= value ? "currentColor" : "none"}
              strokeWidth={1.5}
              style={{ color: (hovered || rating) >= value ? "var(--color-warning)" : "var(--color-muted-foreground)" }}
            />
          </button>
        ))}
      </div>

      <textarea
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        placeholder="Anything else you'd like to add? (optional)"
        rows={2}
        className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      />

      <Button
        size="sm"
        onClick={handleSubmit}
        disabled={rating === 0 || submitFeedback.isPending}
        className="self-end"
      >
        Submit feedback
      </Button>
    </div>
  );
}
