import { createFileRoute, redirect } from "@tanstack/react-router";
import { searchOf } from "@/lib/navigation";

export const Route = createFileRoute("/")({
  beforeLoad: ({ search }) => {
    throw redirect({ to: "/trending", search: searchOf(search) });
  },
});
