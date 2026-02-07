"""Generates the provisioned Grafana dashboards in grafana/dashboards.

The panels share their SQL filters, so the dashboards are generated instead of edited by
hand. Change this file and run it, Grafana picks up the new json within 10 seconds:

    uv run python grafana/build_dashboards.py
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}

SCOPE = (
    "subreddit IN (SELECT subreddit FROM subreddit_groups WHERE group_name = ${group:sqlstring}) "
    "AND $__conditionalAll(subreddit IN (${subreddit:singlequote}), $subreddit) "
    "AND source IN (${source:singlequote})"
)
TERMS = "term IN arrayMap(t -> trimBoth(lower(t)), splitByChar(',', ${terms:sqlstring}))"
# words of the text and of each term, joined by single spaces, so "GPT-5" matches "gpt 5"
TEXT_MATCHES_TERMS = (
    "arrayExists(t -> position("
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(text)), ' '), ' '), "
    "concat(' ', arrayStringConcat(splitByNonAlpha(lower(t)), ' '), ' ')) > 0, "
    "splitByChar(',', ${terms:sqlstring}))"
)


def target(sql: str, table: bool = False) -> dict:
    return {
        "datasource": DS,
        "editorType": "sql",
        "format": 1 if table else 0,
        "queryType": "table" if table else "timeseries",
        "rawSql": sql.strip(),
        "refId": "A",
    }


def panel(kind, title, sql, x, y, w, h, *, description="", table=False, unit=None, **options):
    result = {
        "type": kind,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(sql, table=table)],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    if unit:
        result["fieldConfig"]["defaults"]["unit"] = unit
    if kind == "stat":
        # plain numbers, unless a panel defines what's good and bad
        warn_above = options.pop("warn_above", None)
        result["options"] = {
            "colorMode": "value" if warn_above is not None else "none",
            "graphMode": "none",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        }
        if warn_above is not None:
            result["fieldConfig"]["defaults"]["thresholds"] = {
                "mode": "absolute",
                "steps": [
                    {"color": "green", "value": None},
                    {"color": "orange", "value": warn_above},
                ],
            }
    if series_label := options.pop("series_label", None):
        # name each series after its label ("ai") instead of "per_1000 ai"
        result["fieldConfig"]["defaults"]["displayName"] = f"${{__field.labels.{series_label}}}"
    if kind == "timeseries":
        result["fieldConfig"]["defaults"]["custom"] = {
            "spanNulls": True,
            "lineWidth": 2,
            "fillOpacity": 8,
            "drawStyle": options.pop("draw_style", "line"),
            "stacking": {"mode": options.pop("stacking", "none")},
        }
        result["options"] = {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        }
    result.update(options)
    return result


def query_variable(
    name, label, sql, *, multi=False, include_all=False, default=None, all_value="$__all"
):
    """all_value="$__all" is for $__conditionalAll, None expands "All" to every value."""
    variable = {
        "type": "query",
        "name": name,
        "label": label,
        "datasource": DS,
        "query": sql,
        "definition": sql,
        "refresh": 1,
        "multi": multi,
        "includeAll": include_all,
        "sort": 0,
    }
    if include_all:
        if all_value:
            variable["allValue"] = all_value
        variable["current"] = {"text": ["All"], "value": ["$__all"]}
    elif default:
        variable["current"] = {"text": default, "value": default}
    return variable


def custom_variable(name, label, values, *, default, multi=False, include_all=False):
    options = [{"text": v, "value": v, "selected": v in default} for v in values]
    return {
        "type": "custom",
        "name": name,
        "label": label,
        "query": ",".join(values),
        "options": options,
        "current": {"text": default, "value": default},
        "multi": multi,
        "includeAll": include_all,
    }


def scope_variables():
    return [
        query_variable(
            "group",
            "Group",
            "SELECT DISTINCT group_name FROM subreddit_groups "
            "ORDER BY group_name = 'tracked' DESC, group_name",
            default="tracked",
        ),
        query_variable(
            "subreddit",
            "Subreddits",
            "SELECT subreddit FROM subreddit_groups WHERE group_name = ${group:sqlstring} "
            "ORDER BY subreddit",
            multi=True,
            include_all=True,
        ),
        custom_variable(
            "source",
            "Source",
            ["comment", "post"],
            default=["comment", "post"],
            multi=True,
        ),
    ]


def dashboard(uid, title, description, panels, variables, time_from, refresh=""):
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["wgra"],
        "timezone": "browser",
        "schemaVersion": 41,
        "editable": False,
        "graphTooltip": 1,
        "refresh": refresh,
        "time": {"from": time_from, "to": "now"},
        "templating": {"list": variables},
        "panels": panels,
    }


terms_dashboard = dashboard(
    "wgra-terms",
    "Term explorer",
    "How often terms are mentioned in a group or subreddits, relative to all comments and posts.",
    [
        panel(
            "timeseries",
            "Share of comments and posts mentioning the term (per 1,000)",
            f"""
SELECT t.time AS time, t.term AS term, 1000 * t.docs / s.docs AS per_1000
FROM (
    SELECT $__timeInterval(hour) AS time, term, sum(docs) AS docs
    FROM term_hourly
    WHERE $__timeFilter(hour) AND {TERMS} AND {SCOPE}
    GROUP BY time, term
) AS t
INNER JOIN (
    SELECT $__timeInterval(hour) AS time, sum(docs) AS docs
    FROM scope_hourly
    WHERE $__timeFilter(hour) AND {SCOPE}
    GROUP BY time
) AS s USING time
ORDER BY time
""",
            0,
            0,
            24,
            11,
            description=(
                "Comments and posts that contain the term, per 1,000 comments and posts in the "
                "selected subreddits. Dividing by the total removes the daily and weekly activity "
                "swings, so the line shows the share of the conversation. Separate several terms "
                "with commas."
            ),
            interval="1h",
            series_label="term",
        ),
        panel(
            "timeseries",
            "Mentions",
            f"""
SELECT $__timeInterval(hour) AS time, term, sum(docs) AS mentions
FROM term_hourly
WHERE $__timeFilter(hour) AND {TERMS} AND {SCOPE}
GROUP BY time, term
ORDER BY time
""",
            0,
            11,
            12,
            9,
            description="Comments and posts containing the term (each counts once).",
            interval="1h",
            series_label="term",
            draw_style="bars",
        ),
        panel(
            "timeseries",
            "Distinct authors",
            f"""
SELECT $__timeInterval(hour) AS time, term, uniqCombinedMerge(12)(authors) AS authors
FROM term_hourly
WHERE $__timeFilter(hour) AND {TERMS} AND {SCOPE}
GROUP BY time, term
ORDER BY time
""",
            12,
            11,
            12,
            9,
            description="Different people mentioning the term. Few authors and many mentions "
            "usually means spam or one heated thread.",
            interval="1h",
            draw_style="bars",
            series_label="term",
        ),
        panel(
            "table",
            "Where it is discussed",
            f"""
SELECT t.term AS term, t.subreddit AS subreddit, t.docs AS mentions, t.authors AS authors,
       round(1000 * t.docs / s.docs, 2) AS per_1000
FROM (
    SELECT term, subreddit, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
    FROM term_hourly
    WHERE $__timeFilter(hour) AND {TERMS} AND {SCOPE}
    GROUP BY term, subreddit
) AS t
INNER JOIN (
    SELECT subreddit, sum(docs) AS docs
    FROM scope_hourly
    WHERE $__timeFilter(hour) AND {SCOPE}
    GROUP BY subreddit
) AS s USING subreddit
ORDER BY mentions DESC
LIMIT 100
""",
            0,
            20,
            9,
            12,
            table=True,
            description="Within the selected time range.",
        ),
        panel(
            "table",
            "Recent mentions",
            f"""
SELECT created_at AS time, subreddit, source, substring(text, 1, 400) AS text,
       concat('https://www.reddit.com', permalink) AS link
FROM items
WHERE $__timeFilter(created_at) AND {SCOPE} AND {TEXT_MATCHES_TERMS}
ORDER BY created_at DESC
LIMIT 100
""",
            9,
            20,
            15,
            12,
            table=True,
            description="Raw text is only kept for 48 hours.",
            fieldConfig={
                "defaults": {},
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "link"},
                        "properties": [
                            {
                                "id": "links",
                                "value": [
                                    {
                                        "title": "Open on reddit",
                                        "url": "${__value.raw}",
                                        "targetBlank": True,
                                    }
                                ],
                            },
                            {"id": "custom.width", "value": 90},
                        ],
                    },
                    {
                        "matcher": {"id": "byName", "options": "time"},
                        "properties": [{"id": "custom.width", "value": 160}],
                    },
                    {
                        "matcher": {"id": "byName", "options": "subreddit"},
                        "properties": [{"id": "custom.width", "value": 120}],
                    },
                    {
                        "matcher": {"id": "byName", "options": "source"},
                        "properties": [{"id": "custom.width", "value": 80}],
                    },
                ],
            },
        ),
    ],
    [
        {
            "type": "textbox",
            "name": "terms",
            "label": "Terms (comma separated)",
            "query": "ai, claude, gpt",
            "current": {"text": "ai, claude, gpt", "value": "ai, claude, gpt"},
        },
        *scope_variables(),
    ],
    "now-2d",
)

rising_dashboard = dashboard(
    "wgra-rising",
    "Rising (preview)",
    "A first, simple look at what's rising. The real trend scoring is in Trending now.",
    [
        panel(
            "table",
            "Rising: last 24 hours vs usual",
            f"""
WITH
    (SELECT sum(docs) FROM scope_hourly
     WHERE {SCOPE} AND hour >= now() - INTERVAL 24 HOUR) AS n_now,
    (SELECT sum(docs) FROM scope_hourly
     WHERE {SCOPE}
       AND hour >= now() - INTERVAL 8 DAY AND hour < now() - INTERVAL 24 HOUR) AS n_before,
    (SELECT sum(docs) FROM scope_hourly
     WHERE subreddit = '_sample'
       AND hour >= now() - INTERVAL 8 DAY) AS n_background,
    -- how many comments' worth of weight the reddit-wide share gets in "usual"
    500 AS prior_weight,
    candidates AS (
        SELECT
            term,
            kind,
            sumIf(docs, hour >= now() - INTERVAL 24 HOUR) AS mentions_24h,
            uniqCombinedMergeIf(12)(authors, hour >= now() - INTERVAL 24 HOUR) AS authors_24h,
            sumIf(docs, hour < now() - INTERVAL 24 HOUR) AS mentions_before
        FROM term_hourly
        WHERE {SCOPE} AND kind IN (${{kind:singlequote}}) AND hour >= now() - INTERVAL 8 DAY
        GROUP BY term, kind
        HAVING mentions_24h >= $min_mentions AND authors_24h >= $min_authors
    ),
    background AS (
        SELECT term, kind, sum(docs) AS mentions
        FROM term_hourly
        WHERE subreddit = '_sample'
          AND hour >= now() - INTERVAL 8 DAY
          AND (term, kind) IN (SELECT term, kind FROM candidates)
        GROUP BY term, kind
    )
SELECT
    c.term AS term,
    c.kind AS kind,
    c.mentions_24h AS mentions_24h,
    c.authors_24h AS authors_24h,
    c.mentions_before AS mentions_7d_before,
    b.mentions AS mentions_reddit_sample,
    (c.mentions_before + prior_weight * (b.mentions + 1) / (n_background + 1))
        / (n_before + prior_weight) AS usual_share,
    round(1000 * c.mentions_24h / n_now, 2) AS per_1000_now,
    round(1000 * usual_share, 2) AS per_1000_usual,
    round(c.mentions_24h / n_now / usual_share, 1) AS times_usual
FROM candidates AS c
LEFT JOIN background AS b USING (term, kind)
ORDER BY times_usual DESC, mentions_24h DESC
LIMIT 200
""",
            0,
            0,
            24,
            24,
            table=True,
            description=(
                "times_usual: the share of comments and posts mentioning a term in the last 24 "
                "hours, divided by its usual share. Usual blends the term's share in the 7 days "
                "before with its share in the sample of all of reddit. Without history yet, the "
                "reddit-wide share dominates, so this first shows what is distinctive for the "
                "group and turns into what is rising as history accumulates. Ignores the time "
                "picker. The real trend scoring is on the Trending now dashboard."
            ),
            fieldConfig={
                "defaults": {},
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "usual_share"},
                        "properties": [{"id": "custom.hidden", "value": True}],
                    }
                ],
            },
        ),
    ],
    [
        *scope_variables(),
        custom_variable(
            "kind",
            "Kind",
            ["word", "phrase", "domain", "subreddit"],
            default=["word", "phrase"],
            multi=True,
        ),
        custom_variable(
            "min_mentions", "Min mentions (24h)", ["5", "10", "25", "50", "100"], default="10"
        ),
        custom_variable("min_authors", "Min authors (24h)", ["3", "5", "10", "25"], default="5"),
    ],
    "now-24h",
)

tracked = "subreddit IN (SELECT subreddit FROM subreddit_groups WHERE group_name = 'tracked')"
ingestion_dashboard = dashboard(
    "wgra-ingestion",
    "Ingestion",
    "Is the ingester healthy and complete?",
    [
        panel(
            "stat",
            "Comments + posts stored, last 24h",
            f"SELECT sum(docs) FROM scope_hourly "
            f"WHERE {tracked} AND hour >= now() - INTERVAL 24 HOUR",
            0,
            0,
            6,
            5,
            table=True,
            description="From tracked subreddits, without the r/all sample.",
        ),
        panel(
            "stat",
            "Requests, last 10 minutes",
            "SELECT count() FROM polls WHERE ts > now() - INTERVAL 10 MINUTE",
            6,
            0,
            6,
            5,
            table=True,
            description="Reddit allows 1000 requests per 10 minutes per client id.",
        ),
        panel(
            "stat",
            "Gaps, last 24h",
            "SELECT sum(gap) FROM polls WHERE ts > now() - INTERVAL 24 HOUR",
            12,
            0,
            6,
            5,
            table=True,
            warn_above=1,
            description="Polls that found a full listing of unseen items: some items were probably "
            "missed. The feed then polls more often.",
        ),
        panel(
            "stat",
            "Share of all reddit comments sampled",
            "SELECT sum(new_items) / sum(id_span) FROM polls "
            "WHERE background AND id_span > 0 AND $__timeFilter(ts)",
            18,
            0,
            6,
            5,
            table=True,
            unit="percentunit",
            description="The r/all sample: new comments we got vs how far reddit's comment ids "
            "advanced (roughly all comments posted on reddit).",
        ),
        panel(
            "timeseries",
            "New items per minute",
            """
SELECT $__timeInterval(ts) AS time, feed, sum(new_items) / ($__interval_s / 60) AS per_minute
FROM polls
WHERE $__timeFilter(ts)
GROUP BY time, feed
ORDER BY time
""",
            0,
            5,
            12,
            9,
            interval="1m",
            series_label="feed",
        ),
        panel(
            "timeseries",
            "Requests per minute",
            """
SELECT $__timeInterval(ts) AS time,
       count() / ($__interval_s / 60) AS requests,
       countIf(status != 200) / ($__interval_s / 60) AS errors,
       sum(gap) / ($__interval_s / 60) AS gaps
FROM polls
WHERE $__timeFilter(ts)
GROUP BY time
ORDER BY time
""",
            12,
            5,
            12,
            9,
            interval="1m",
        ),
        panel(
            "table",
            "Feeds, last hour",
            """
SELECT feed, count() AS polls, countIf(status != 200) AS errors, sum(new_items) AS new_items,
       sum(gap) AS gaps, round(avg(interval_s), 1) AS poll_every_s,
       round(argMax(rate, ts) * 60) AS items_per_minute, max(ts) AS last_poll
FROM polls
WHERE ts > now() - INTERVAL 1 HOUR
GROUP BY feed
ORDER BY feed
""",
            0,
            14,
            12,
            8,
            table=True,
        ),
        panel(
            "table",
            "Storage",
            """
SELECT table, sum(rows) AS rows, formatReadableSize(sum(bytes_on_disk)) AS size
FROM system.parts
WHERE active AND database = currentDatabase()
GROUP BY table
ORDER BY sum(bytes_on_disk) DESC
""",
            12,
            14,
            12,
            8,
            table=True,
        ),
        panel(
            "table",
            "Tracked subreddits, last 24h",
            f"""
SELECT subreddit,
       sumIf(docs, source = 'comment') AS comments,
       sumIf(docs, source = 'post') AS posts,
       uniqCombinedMerge(12)(authors) AS authors
FROM scope_hourly
WHERE {tracked} AND hour >= now() - INTERVAL 24 HOUR
GROUP BY subreddit
ORDER BY comments DESC
""",
            0,
            22,
            24,
            12,
            table=True,
        ),
    ],
    [],
    "now-6h",
    refresh="1m",
)

# What the analyzer found (wgra analyze, every 15 minutes). A scope is a tracked subreddit
# ("r/technology") or a group ("tech"), the dashboard shows a group and its subreddits.
TREND_SCOPES = "scope IN (${scope:singlequote})"
LATEST_RUN = (
    "(SELECT max(detected_at) FROM trends WHERE horizon = ${horizon:sqlstring}) AS latest_run"
)
LATEST_TRENDS = (
    "horizon = ${horizon:sqlstring} AND detected_at = latest_run AND "
    f"{TREND_SCOPES} AND kind IN (${{kind:singlequote}}) "
    "AND (subsumed_by = '' OR ${subsumed:sqlstring} = 'show')"
)


def explore_url(scope: str = "scope") -> str:
    """SQL for the term explorer url of a trend: its group, or its subreddit."""
    return (
        "concat('/d/wgra-terms?var-terms=', encodeURLFormComponent(term), "
        f"if(startsWith({scope}, 'r/'), "
        "concat('&var-group=tracked&var-subreddit=', "
        f"encodeURLFormComponent(substring({scope}, 3))), "
        f"concat('&var-group=', encodeURLFormComponent({scope}))), '&from=now-7d&to=now')"
    )


# each trend's hourly mentions in the group in the week before the run, for the sparklines
SPARKLINES = f"""
WITH {LATEST_RUN}
SELECT hour AS time, term, sum(docs) AS mentions
FROM term_hourly
WHERE hour > latest_run - INTERVAL 7 DAY AND hour <= latest_run
  AND subreddit IN (SELECT subreddit FROM subreddit_groups WHERE group_name = ${{group:sqlstring}})
  AND (kind, term) IN (SELECT kind, term FROM trends WHERE {LATEST_TRENDS})
GROUP BY time, term
ORDER BY time
"""


def with_sparklines(table_panel: dict) -> dict:
    """Adds a column with each term's mentions over the last week, as a sparkline."""
    table_panel["targets"].append({**target(SPARKLINES), "refId": "B"})
    columns = [
        "term",
        "scope",
        "score",
        "times_usual",
        "mentions",
        "authors",
        "Trend #B",
        "breadth",
        "kind",
        "mentions_before",
        "alert",
        "subsumed_by",
        "explore",
    ]
    table_panel["transformations"] = [
        # one row per term, with its series as a sparkline
        {"id": "timeSeriesTable", "options": {}},
        {"id": "joinByField", "options": {"byField": "term", "mode": "outerTabular"}},
        # the join names the table's columns after their query ("scope A")
        {
            "id": "organize",
            "options": {
                "renameByName": {
                    **{f"{column} A": column for column in columns},
                    "Trend #B": "last 7 days",
                },
                "indexByName": {
                    name: index
                    for index, column in enumerate(columns)
                    for name in (column, f"{column} A")
                },
            },
        },
    ]
    table_panel["options"] = {"sortBy": [{"displayName": "score", "desc": True}]}
    table_panel["fieldConfig"]["overrides"].append(
        {
            "matcher": {"id": "byName", "options": "last 7 days"},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "sparkline", "hideValue": True}},
                {"id": "custom.width", "value": 200},
            ],
        }
    )
    return table_panel


def link_to_explorer(column: str) -> dict:
    """A table override: clicking `column` opens the term explorer (url in "explore")."""
    return {
        "matcher": {"id": "byName", "options": column},
        "properties": [
            {
                "id": "links",
                "value": [
                    {"title": "Open in the term explorer", "url": "${__data.fields.explore}"}
                ],
            }
        ],
    }


def hidden(column: str) -> dict:
    return {
        "matcher": {"id": "byName", "options": column},
        "properties": [{"id": "custom.hidden", "value": True}],
    }


def width(column: str, pixels: int) -> dict:
    return {
        "matcher": {"id": "byName", "options": column},
        "properties": [{"id": "custom.width", "value": pixels}],
    }


trending_dashboard = dashboard(
    "wgra-trending",
    "Trending now",
    "Terms mentioned far more than usual, scored every 15 minutes by wgra analyze.",
    [
        panel(
            "stat",
            "Last run",
            "SELECT toUnixTimestamp(max(detected_at)) * 1000 FROM trends "
            "WHERE horizon = ${horizon:sqlstring}",
            0,
            0,
            6,
            4,
            table=True,
            unit="dateTimeFromNow",
            description="When wgra analyze last scored this horizon. It runs every 15 minutes.",
        ),
        panel(
            "stat",
            "Days of history",
            f"""
SELECT max(reference_days)
FROM trends
WHERE horizon = ${{horizon:sqlstring}} AND {TREND_SCOPES}
  AND detected_at = (SELECT max(detected_at) FROM trends WHERE horizon = ${{horizon:sqlstring}})
""",
            6,
            0,
            6,
            4,
            table=True,
            description="Days of data the window is compared with, up to 28. With less than 3 "
            "days there are no alerts, and on the first day the window is compared with the "
            "share of the term on all of reddit (the r/all sample): what's distinctive, not "
            "what's rising.",
        ),
        panel(
            "stat",
            "Trending terms",
            f"""
WITH {LATEST_RUN}
SELECT uniqExact(term) FROM trends WHERE {LATEST_TRENDS}
""",
            12,
            0,
            6,
            4,
            table=True,
            description="Distinct terms trending in the selected scopes in the latest run.",
        ),
        panel(
            "stat",
            "Alerts sent, last 24h",
            "SELECT count() FROM trends WHERE alert = 'sent' "
            "AND detected_at > now() - INTERVAL 24 HOUR",
            18,
            0,
            6,
            4,
            table=True,
            description="Instant alerts to ntfy, in all scopes. At most 5 a day by default.",
        ),
        with_sparklines(
            panel(
                "table",
                "Trending now",
                f"""
WITH {LATEST_RUN}
SELECT
    scope,
    term,
    kind,
    round(z, 1) AS score,
    if(is_new, 'new', toString(round(ratio, 1))) AS times_usual,
    mentions,
    authors,
    if(scope_type = 'group', concat(toString(breadth), '/', toString(members)), '')
        AS breadth,
    reference_mentions AS mentions_before,
    alert,
    subsumed_by,
    {explore_url()} AS explore
FROM trends FINAL
WHERE {LATEST_TRENDS}
ORDER BY z DESC
LIMIT 200
""",
                0,
                4,
                24,
                14,
                table=True,
                description=(
                    "The latest run. score: strength of the evidence (z of the weighted log odds, "
                    "see docs/ARCHITECTURE-V2.md §4.2), what trends are ranked by. times_usual: "
                    "the share of comments and posts mentioning the term in the window, divided "
                    "by its share in the 28 days before. new: barely mentioned before. breadth: "
                    "for a group, in how many of its subreddits the term trends, of those "
                    "mentioning it. subsumed_by: a phrase that explains this burst ('pro' "
                    "because of 'vision pro'), shown when Subsumed is set to show. Click a term "
                    "to open it in the term explorer."
                ),
                fieldConfig={
                    "defaults": {},
                    "overrides": [
                        link_to_explorer("term"),
                        hidden("explore"),
                        width("scope", 170),
                        width("score", 70),
                        width("times_usual", 100),
                        width("mentions", 90),
                        width("authors", 80),
                        width("breadth", 80),
                        width("kind", 70),
                        width("mentions_before", 130),
                        width("alert", 80),
                    ],
                },
            ),
        ),
        panel(
            "timeseries",
            "The top trends over time (per 1,000 comments and posts in the group)",
            f"""
WITH {LATEST_RUN}
SELECT t.time AS time, t.term AS term, 1000 * t.docs / s.docs AS per_1000
FROM (
    SELECT $__timeInterval(hour) AS time, term, sum(docs) AS docs
    FROM term_hourly
    WHERE $__timeFilter(hour)
      AND subreddit IN (SELECT subreddit FROM subreddit_groups
                        WHERE group_name = ${{group:sqlstring}})
      AND (kind, term) IN (
          SELECT kind, term FROM trends
          WHERE {LATEST_TRENDS} AND subsumed_by = ''
          GROUP BY kind, term ORDER BY max(z) DESC LIMIT 8
      )
    GROUP BY time, term
) AS t
INNER JOIN (
    SELECT $__timeInterval(hour) AS time, sum(docs) AS docs
    FROM scope_hourly
    WHERE $__timeFilter(hour)
      AND subreddit IN (SELECT subreddit FROM subreddit_groups
                        WHERE group_name = ${{group:sqlstring}})
    GROUP BY time
) AS s USING time
ORDER BY time
""",
            0,
            18,
            24,
            10,
            description="The 8 strongest trends of the latest run, as a share of all comments "
            "and posts in the group's subreddits.",
            interval="1h",
            series_label="term",
        ),
        panel(
            "table",
            "Strongest trends of the last 24 hours (the daily digest)",
            f"""
SELECT
    term,
    argMax(scope, z) AS strongest_in,
    round(max(z), 1) AS score,
    if(argMax(is_new, z), 'new', toString(round(argMax(ratio, z), 1))) AS times_usual,
    argMax(mentions, z) AS mentions,
    min(detected_at) AS first_seen,
    max(detected_at) AS last_seen,
    arrayStringConcat(arraySort(groupUniqArray(horizon)), ', ') AS horizons,
    {explore_url("strongest_in")} AS explore
FROM trends
WHERE detected_at > now() - INTERVAL 24 HOUR AND {TREND_SCOPES}
  AND kind IN (${{kind:singlequote}}) AND subsumed_by = ''
GROUP BY term
ORDER BY max(z) DESC
LIMIT 100
""",
            0,
            28,
            12,
            12,
            table=True,
            description="Each term at its strongest, in any of the selected scopes and either "
            "horizon. The daily digest sends the top 10 of each group.",
            fieldConfig={
                "defaults": {},
                "overrides": [link_to_explorer("term"), hidden("explore")],
            },
        ),
        panel(
            "table",
            "Alerts, last 14 days",
            f"""
SELECT detected_at AS time, horizon, scope, term, alert, round(z, 1) AS score,
       if(is_new, 'new', toString(round(ratio, 1))) AS times_usual, mentions, authors,
       {explore_url()} AS explore
FROM trends FINAL
WHERE alert != '' AND detected_at > now() - INTERVAL 14 DAY AND {TREND_SCOPES}
ORDER BY detected_at DESC
LIMIT 200
""",
            12,
            28,
            12,
            12,
            table=True,
            description="Trends strong enough for an instant alert, and what happened: sent, "
            "failed, capped (daily limit reached), cooldown (alerted in the last 72h), warmup "
            "(less than 3 days of history), skipped (scope never alerts), muted (a run without "
            "notifications). Only one scope per term and run gets a status.",
            fieldConfig={
                "defaults": {},
                "overrides": [link_to_explorer("term"), hidden("explore"), width("time", 160)],
            },
        ),
    ],
    [
        query_variable(
            "group",
            "Group",
            "SELECT DISTINCT group_name FROM subreddit_groups "
            "ORDER BY group_name = 'tracked' DESC, group_name",
            default="tracked",
        ),
        query_variable(
            "scope",
            "Scopes",
            "SELECT scope FROM ("
            "SELECT ${group:sqlstring} AS scope, 0 AS position "
            "UNION ALL SELECT concat('r/', subreddit), 1 FROM subreddit_groups "
            "WHERE group_name = ${group:sqlstring}) ORDER BY position, scope",
            multi=True,
            include_all=True,
            all_value=None,
        ),
        custom_variable("horizon", "Horizon", ["24h", "6h"], default="24h"),
        custom_variable(
            "kind",
            "Kind",
            ["word", "phrase", "domain", "subreddit"],
            default=["word", "phrase", "domain", "subreddit"],
            multi=True,
        ),
        custom_variable("subsumed", "Subsumed", ["hide", "show"], default="hide"),
    ],
    "now-7d",
    refresh="5m",
)


OUT.mkdir(parents=True, exist_ok=True)
for name, board in [
    ("trending", trending_dashboard),
    ("term-explorer", terms_dashboard),
    ("rising", rising_dashboard),
    ("ingestion", ingestion_dashboard),
]:
    (OUT / f"{name}.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n")
    print("wrote", OUT / f"{name}.json")
