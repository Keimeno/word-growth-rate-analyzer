/** A term or scope as a path segment for the API: encoded, but its slashes kept, since the
 * API takes the rest of the path (`/terms/repo/ollama/ollama`). */
export function pathPart(text: string): string {
  return encodeURIComponent(text).replaceAll("%2F", "/");
}

/** Where a term is searched for on its platform. */
export function platformSearch(term: string, scope: string): string {
  const channel = scope.match(/^r\/([\w]+)$/);
  const query = encodeURIComponent(term);
  return channel
    ? `https://www.reddit.com/r/${channel[1]}/search/?q=${query}&restrict_sr=1&sort=new`
    : `https://www.reddit.com/search/?q=${query}&sort=new`;
}
