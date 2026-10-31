// The shell: navigation, the scope every page shares, the theme, the term drawer.
import { html, render, useCallback, useEffect, useState } from "./vendor/preact-htm.js";
import { href, readRoute, setParams, useApi, useRoute } from "./lib.js";
import { grafanaLink } from "./grafana.js";
import { TermDrawer } from "./term.js";
import { NowPage } from "./pages/now.js";
import { LongTermPage } from "./pages/long-term.js";
import { IntentsPage } from "./pages/intents.js";
import { EarlyWarningPage } from "./pages/early-warning.js";
import { ExplorePage } from "./pages/explore.js";
import { HealthPage } from "./pages/health.js";

const PAGES = [
  ["now", "Trending", NowPage],
  ["long-term", "Long-term", LongTermPage],
  ["intents", "Why people switch", IntentsPage],
  ["early-warning", "Early warning", EarlyWarningPage],
  ["explore", "Explore", ExplorePage],
  ["health", "Collection", HealthPage],
];
// pages that look at one group or channel, and keep it when switching between them
const SCOPED = new Set(["now", "long-term", "intents", "explore"]);

function initialScope() {
  try {
    return localStorage.getItem("scope") || "reddit";
  } catch (_) {
    return "reddit";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "");
  const dark = theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const flip = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (_) {}
    setTheme(next);
  };
  return html`<button type="button" class="icon-button" onClick=${flip} aria-label=${dark ? "Light mode" : "Dark mode"}
    title=${dark ? "Light mode" : "Dark mode"}>${dark ? "☀" : "☾"}</button>`;
}

function App() {
  const route = useRoute();
  const meta = useApi("meta", {}, { refresh: 10 * 60e3 });
  const config = useApi("config", {});
  const [drawer, setDrawer] = useState(null);
  const page = PAGES.find(([key]) => key === route.page) || PAGES[0];
  const [key, , Page] = page;

  // the scope is in the url, so links keep it; the last one picked is the default
  const scope = route.params.scope || initialScope();
  const setScope = useCallback((next) => {
    try {
      localStorage.setItem("scope", next);
    } catch (_) {}
    // channels and scopes belong to the old scope
    setParams({ scope: next, channels: undefined, scopes: undefined });
  }, []);
  useEffect(() => {
    document.title = `${page[1]} · Undercurrent`;
    setDrawer(null);
    scrollTo(0, 0);
  }, [key]);

  const openTerm = useCallback((target) => setDrawer(target), []);
  const params = route.params;
  const grafana = grafanaLink(config.data, key === "now" && params.view === "quick" ? "rising" : key, {
    ...(SCOPED.has(key) ? { scope } : {}),
    ...params,
  });

  return html`
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href=${href("now", { scope })}>
          <span class="brand-mark"><svg width="18" height="18" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M4 20c3.5-7 7.5-7 11 0s7.5 7 11 0" stroke="white" stroke-width="3.2" fill="none" stroke-linecap="round" /></svg></span>
          <span>Undercurrent</span>
        </a>
        <nav class="nav" aria-label="Pages">
          ${PAGES.map(([pageKey, label]) => html`<a href=${href(pageKey, SCOPED.has(pageKey) ? { scope } : {})}
            aria-current=${pageKey === key ? "page" : undefined}>${label}</a>`)}
        </nav>
        <div class="top-actions">
          <a class="icon-button" href=${grafana} target="_blank" rel="noopener"
            title="The same view in Grafana, with every panel and setting">
            <span class="label">Pro mode</span> ↗</a>
          <${ThemeToggle} />
        </div>
      </div>
    </header>
    <main>
      <${Page} params=${params} scope=${scope} setScope=${setScope} meta=${meta.data}
        config=${config.data} openTerm=${openTerm} />
    </main>
    ${drawer && html`<${TermDrawer} key=${`${drawer.term}|${drawer.scope}`} target=${drawer} config=${config.data}
      onClose=${() => setDrawer(null)} />`}`;
}

if (!location.hash) history.replaceState(null, "", href(readRoute().page, {}));
render(html`<${App} />`, document.getElementById("app"));
