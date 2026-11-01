/** Pins: a short list of terms followed on purpose, the same on every device. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pin, PinOff } from "lucide-react";
import { getPinsQueryKey, pin, unpin, usePins } from "@/api/generated/endpoints";
import { Button } from "./ui/button";

export function usePinned(): Set<string> {
  const pins = usePins(undefined, { query: { staleTime: 60_000 } });
  return new Set((pins.data ?? []).map((pin) => `${pin.kind}|${pin.term}`));
}

export function PinButton({ kind, term, scope }: { kind: string; term: string; scope: string }) {
  const queryClient = useQueryClient();
  const pinned = usePinned().has(`${kind}|${term}`);
  const toggle = useMutation({
    mutationFn: async (): Promise<void> => {
      if (pinned) await unpin({ kind, term });
      else await pin({ kind, term, scope });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: getPinsQueryKey() }),
  });
  return (
    <Button
      size="sm"
      variant={pinned ? "secondary" : "outline"}
      aria-pressed={pinned}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate()}
    >
      {pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
      {pinned ? "Unpin" : "Pin"}
    </Button>
  );
}
