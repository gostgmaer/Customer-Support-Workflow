"use client";

import { ShoppingCart } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

import { useWooCommerceLookup } from "../hooks";

export function WooCommerceLookupPanel() {
  const [orderNumber, setOrderNumber] = useState("");
  const lookup = useWooCommerceLookup();

  return (
    <div className="rounded-md border border-border p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShoppingCart className="size-4 text-muted-foreground" aria-hidden="true" />
        Look up in WooCommerce
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (orderNumber.trim()) lookup.mutate(orderNumber.trim());
        }}
        className="mt-2 flex gap-2"
      >
        <Input
          value={orderNumber}
          onChange={(e) => setOrderNumber(e.target.value)}
          placeholder="Order number"
          aria-label="WooCommerce order number"
        />
        <Button type="submit" variant="outline" isLoading={lookup.isPending}>
          Look up
        </Button>
      </form>

      {lookup.isSuccess && (
        <div className="mt-3 text-sm">
          {lookup.data ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              <dt className="text-muted-foreground">Order</dt>
              <dd>#{lookup.data.number}</dd>
              <dt className="text-muted-foreground">Status</dt>
              <dd>{lookup.data.status}</dd>
              <dt className="text-muted-foreground">Total</dt>
              <dd>
                {lookup.data.total} {lookup.data.currency}
              </dd>
            </dl>
          ) : (
            <p className="text-muted-foreground">No order found with that number.</p>
          )}
        </div>
      )}
    </div>
  );
}
