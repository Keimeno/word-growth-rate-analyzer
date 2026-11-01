export const WORD_KINDS = ["word", "phrase", "domain", "subreddit"] as const;
export const INTENT_KINDS = ["switch", "considering", "alternative", "complaint", "need"] as const;
export const ALL_KINDS = [...WORD_KINDS, ...INTENT_KINDS] as const;
export type Kind = (typeof ALL_KINDS)[number];

export const KIND_LABELS: Record<string, string> = {
  word: "Words",
  phrase: "Phrases",
  domain: "Links",
  subreddit: "Subreddits",
  switch: "Switches",
  considering: "Considering",
  alternative: "Alternatives",
  complaint: "Complaints",
  need: "Needs",
};

/** The kind of an intent's term: "complaint: reddit" is a complaint, "a → b" a switch. */
export function intentKind(term: string): string | null {
  const at = term.indexOf(": ");
  if (at > 0) return term.slice(0, at);
  return term.includes(" → ") ? "switch" : null;
}

/** What an intent is about: "complaint: reddit" is about reddit. */
export function intentEntity(term: string): string {
  const at = term.indexOf(": ");
  return at > 0 ? term.slice(at + 2) : term;
}
