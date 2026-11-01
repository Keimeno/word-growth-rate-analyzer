import { ExternalLink } from "lucide-react";
import type { Mention } from "@/api/generated/model";
import { ago, formatDateTime } from "@/lib/format";
import { EmptyState } from "./Panel";

/** Words of `terms` in `text` marked, matching like the API: case and punctuation aside. */
function highlight(text: string, terms: readonly string[]) {
  const words = terms
    .flatMap((term) => term.toLowerCase().split(/[^\p{L}\p{N}]+/u))
    .filter((word) => word.length > 1);
  if (!words.length) return text;
  const pattern = new RegExp(
    `(?<![\\p{L}\\p{N}])(${words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})(?![\\p{L}\\p{N}])`,
    "giu",
  );
  return text.split(pattern).map((part, index) =>
    index % 2 === 1 ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: parts of one string, in order
      <mark key={index} className="rounded-xs bg-primary-wash px-0.5 text-primary-ink">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

/** Comments and posts, the newest first: where, when, the text with the terms marked. */
export function Comments({
  mentions,
  terms = [],
  found,
}: {
  mentions: ReadonlyArray<Pick<Mention, "time" | "channel" | "doc_type" | "text" | "url">>;
  terms?: readonly string[];
  /** the intents found in each comment, shown under it */
  found?: (index: number) => readonly string[] | undefined;
}) {
  if (!mentions.length) {
    return (
      <EmptyState title="No comments or posts in the last 48 hours">
        Raw text is kept for 48 hours only; the counts above reach back further.
      </EmptyState>
    );
  }
  return (
    <ul className="divide-y divide-border">
      {mentions.map((mention, index) => (
        <li key={`${mention.url}-${index}`} className="px-4 py-2.5">
          <div className="flex items-center gap-2 text-xs text-ink-muted">
            <span className="font-medium text-ink-secondary">{mention.channel}</span>
            <span>{mention.doc_type}</span>
            <span title={formatDateTime(mention.time)}>{ago(mention.time)}</span>
            {mention.url && (
              <a
                href={mention.url}
                target="_blank"
                rel="noreferrer noopener"
                className="ml-auto inline-flex items-center gap-1 hover:text-primary"
              >
                Open <ExternalLink className="size-3" />
              </a>
            )}
          </div>
          <p className="mt-1 text-sm leading-5 break-words text-ink line-clamp-4">
            {highlight(mention.text, terms)}
          </p>
          {found?.(index)?.length ? (
            <p className="mt-1 text-xs text-ink-muted">
              Found: <span className="term">{found(index)?.join(", ")}</span>
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
