// The comments and posts behind a term or an intent, from the last 48 hours.
import { html } from "./vendor/preact-htm.js";
import { ago, formatDateTime, intentEntity, useApi } from "./lib.js";
import { Badge, Empty, ExternalLink } from "./ui.js";

/**
 * intent: the comments an intent was found in (exact), else those whose words contain the
 * terms. `term` is one term or intent; `kinds` narrows intents when no term is given.
 */
export function Comments({ intent, term, terms, scope, kinds, channels, doc_types, limit = 50 }) {
  const state = useApi(
    intent ? "intents-examples" : "explore-mentions",
    intent
      ? { scope, term: term || "", intent_kinds: kinds, channels, doc_types }
      : { scope, terms: terms || term, range: "48h", channels, doc_types }
  );
  const { data, error } = state;
  if (error && !data) return html`<div class="error">Couldn't load comments: ${error.message}</div>`;
  if (!data) return html`<div class="loading">Loading…</div>`;
  if (!data.length) {
    return html`<${Empty} title="No comments from the last 48 hours">
      Raw text is deleted after 48 hours, as Reddit asks of API users, so older mentions only exist as counts.
    <//>`;
  }
  const highlight = intent ? [] : String(terms || term).split(",").map((t) => t.trim()).filter(Boolean);
  return html`<div class=${`comments${state.loading ? " refreshing" : ""}`}>
    ${data.slice(0, limit).map((row) => html`<article class="comment">
      <div class="comment-meta">
        <span title=${formatDateTime(row.time)}>${ago(row.time)}</span>
        <span>·</span><span>${row.channel}</span>
        ${row.doc_type === "post" && html`<${Badge}>post<//>`}
        ${(row.found || []).map((found) => html`<${Badge} tone="accent">${found}<//>`)}
        <span style="margin-left:auto"><${ExternalLink} href=${row.url}>Open<//></span>
      </div>
      <div class="comment-text">${marked(row.text, highlight)}</div>
    </article>`)}
    ${data.length > limit && html`<div class="table-more muted small">${data.length - limit} more not shown</div>`}
  </div>`;
}

/** The text with the terms' first occurrences marked, matched case-insensitively. */
function marked(text, terms) {
  if (!terms.length) return text;
  const lower = text.toLowerCase();
  const spans = [];
  for (const term of terms) {
    const needle = intentEntity(term).toLowerCase();
    if (needle.length < 2) continue;
    let at = lower.indexOf(needle);
    while (at >= 0 && spans.length < 20) {
      spans.push([at, at + needle.length]);
      at = lower.indexOf(needle, at + needle.length);
    }
  }
  spans.sort((a, b) => a[0] - b[0]);
  const parts = [];
  let position = 0;
  for (const [start, end] of spans) {
    if (start < position) continue;
    parts.push(text.slice(position, start), html`<mark>${text.slice(start, end)}</mark>`);
    position = end;
  }
  parts.push(text.slice(position));
  return parts;
}
