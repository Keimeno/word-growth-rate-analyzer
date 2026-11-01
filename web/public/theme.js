// The theme before the first paint: the reader's choice, else the system's. A file of its own
// rather than inline, so the Content Security Policy needs no 'unsafe-inline'.
(() => {
  let choice = null;
  try {
    choice = localStorage.getItem("undercurrent.theme");
  } catch {}
  const dark =
    choice === "dark" || (choice !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();
