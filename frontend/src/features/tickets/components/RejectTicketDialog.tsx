"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";

export function RejectTicketDialog({
  open,
  onClose,
  onConfirm,
  isSubmitting,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  isSubmitting: boolean;
}) {
  const [reason, setReason] = useState("");

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Reject this ticket"
      description="The customer will not see this reason directly, but it's recorded in the audit trail."
    >
      <Label htmlFor="reject-reason">Reason (optional)</Label>
      <Textarea
        id="reject-reason"
        rows={3}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="e.g. Refund amount exceeds policy limit for this order"
      />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" isLoading={isSubmitting} onClick={() => onConfirm(reason)}>
          Reject ticket
        </Button>
      </div>
    </Dialog>
  );
}
