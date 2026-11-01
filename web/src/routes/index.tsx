import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: Home,
});

function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="type-title-lg">Undercurrent</h1>
      <p className="mt-2 text-ink-secondary">Early signals in online conversation.</p>
    </main>
  );
}
