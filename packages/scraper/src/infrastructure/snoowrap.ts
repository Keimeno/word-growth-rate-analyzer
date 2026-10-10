import Snoowrap from 'snoowrap';

// node >= 18 ships fetch, but the installed @types/node predates it
declare const fetch: (
  url: string,
  init: {method: string; headers: Record<string, string>; body: string}
) => Promise<{
  ok: boolean;
  status: number;
  json: () => Promise<{access_token: string}>;
}>;

const {
  REDDIT_USER_AGENT,
  REDDIT_CLIENT_ID,
  REDDIT_CLIENT_SECRET,
  REDDIT_USERNAME,
  REDDIT_PASSWORD,
} = process.env as {[key: string]: string};

// app-only tokens can't be refreshed by snoowrap, so we request a new one
// shortly before reddit lets the current one expire (expires_in is 24h)
const TOKEN_LIFETIME = 1000 * 60 * 60 * 23;

// don't hammer the token endpoint when the authentication keeps failing
const AUTH_RETRY_DELAY = 1000 * 60;

let client: Promise<Snoowrap> | null = null;
let clientCreatedAt = 0;

const createClient = async (): Promise<Snoowrap> => {
  // a username and password are only required for the password grant,
  // reading public listings works with the client credentials alone
  if (REDDIT_USERNAME && REDDIT_PASSWORD) {
    return new Snoowrap({
      userAgent: REDDIT_USER_AGENT,
      clientId: REDDIT_CLIENT_ID,
      clientSecret: REDDIT_CLIENT_SECRET,
      username: REDDIT_USERNAME,
      password: REDDIT_PASSWORD,
    });
  }

  // snoowrap.fromApplicationOnlyAuth sends the token request without a
  // user agent, which reddit blocks, so we request the token ourselves
  const response = await fetch('https://www.reddit.com/api/v1/access_token', {
    method: 'POST',
    headers: {
      'User-Agent': REDDIT_USER_AGENT,
      'Content-Type': 'application/x-www-form-urlencoded',
      Authorization: `Basic ${Buffer.from(
        `${REDDIT_CLIENT_ID}:${REDDIT_CLIENT_SECRET}`
      ).toString('base64')}`,
    },
    body: 'grant_type=client_credentials',
  });

  if (!response.ok) {
    throw new Error(`Failed to get a reddit access token (${response.status})`);
  }

  const {access_token: accessToken} = await response.json();

  return new Snoowrap({
    userAgent: REDDIT_USER_AGENT,
    clientId: REDDIT_CLIENT_ID,
    clientSecret: REDDIT_CLIENT_SECRET,
    accessToken,
  });
};

export const getClient = (): Promise<Snoowrap> => {
  if (client === null || Date.now() - clientCreatedAt > TOKEN_LIFETIME) {
    clientCreatedAt = Date.now();
    client = createClient().catch(e => {
      // allow a later poll to retry the authentication
      setTimeout(() => (client = null), AUTH_RETRY_DELAY);
      throw e;
    });
  }

  return client;
};
