"""Generates the provisioned Grafana dashboards in grafana/dashboards.

The panels share their SQL filters, so the dashboards are generated instead of edited by
hand. Change this file and run it, Grafana picks up the new json within 10 seconds:

    uv run python grafana/build_dashboards.py
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "grafana-clickhouse-datasource", "uid": "clickhouse"}

# The scope picker ("group") takes a group or a channel: every group, the platforms' first
# ("reddit": every tracked subreddit), then every analyzed channel ("r/technology", "r/all").
SCOPES = (
    "SELECT name FROM ("
    "SELECT DISTINCT group_name AS name, 0 AS position, "
    "group_name IN (SELECT platform FROM channels) AS platform FROM channel_groups "
    "UNION ALL SELECT channel, 1, false FROM channels WHERE analyzed) "
    "ORDER BY position, platform DESC, name"
)
# the channels of the picked scope: a group's, or the channel itself
GROUP_CHANNELS = (
    "SELECT channel FROM channel_groups WHERE group_name = ${group:sqlstring} "
    "UNION ALL SELECT channel FROM channels WHERE channel = ${group:sqlstring}"
)
SCOPE = (
    f"channel IN ({GROUP_CHANNELS}) "
    "AND $__conditionalAll(channel IN (${channel:singlequote}), $channel) "
    "AND $__conditionalAll(doc_type IN (${doc_type:singlequote}), $doc_type)"
)
# the kinds of intents (docs/ARCHITECTURE.md §4.7), terms like words otherwise
INTENT_KINDS = ["switch", "alternative", "complaint", "need", "considering"]
INTENT_KIND_LIST = ", ".join(f"'{kind}'" for kind in INTENT_KINDS)
TERM_LIST = "arrayMap(t -> trimBoth(lower(t)), splitByChar(',', ${terms:sqlstring}))"
# the platform's background channel, the prior of its scores (r/all)
BACKGROUND = "SELECT channel FROM channels WHERE background"
TERMS = f"term IN {TERM_LIST}"
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


def group_variable():
    return query_variable("group", "Group or channel", SCOPES, default="reddit")


def scope_variables():
    return [
        group_variable(),
        query_variable(
            "channel",
            "Channels",
            f"SELECT channel FROM ({GROUP_CHANNELS}) ORDER BY channel",
            multi=True,
            include_all=True,
        ),
        query_variable(
            "doc_type",
            "Type",
            "SELECT DISTINCT doc_type FROM scope_hourly ORDER BY doc_type",
            multi=True,
            include_all=True,
        ),
    ]


def scopes_variable():
    """The picked group and its channels, or the picked channel, for the tables of trends."""
    return query_variable(
        "scope",
        "Scopes",
        "SELECT scope FROM ("
        "SELECT ${group:sqlstring} AS scope, 0 AS position "
        "UNION ALL SELECT channel, 1 FROM channel_groups WHERE group_name = ${group:sqlstring}) "
        "ORDER BY position, scope",
        multi=True,
        include_all=True,
        all_value=None,
    )


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


# The term explorer's buckets: auto (Grafana's interval), hour, day or week (ISO weeks,
# Monday to Sunday UTC). Days and weeks come from term_daily, which is kept forever,
# hours from term_hourly (180 days).
DAILY = "${bucket:sqlstring} IN ('day', 'week')"
HOUR_BUCKET = "if(${bucket:sqlstring} = 'hour', hour, $__timeInterval(hour))"
DAY_BUCKET = (
    "if(${bucket:sqlstring} = 'week', toDateTime(toMonday(day), 'UTC'), toDateTime(day, 'UTC'))"
)
TOTAL_BUCKET = (
    "multiIf(${bucket:sqlstring} = 'week', toDateTime(toMonday(hour), 'UTC'), "
    "${bucket:sqlstring} = 'day', toStartOfDay(hour), "
    "${bucket:sqlstring} = 'hour', hour, $__timeInterval(hour))"
)
# daily buckets count whole days, the comments in them too
DAYS = "day >= toDate($__fromTime) AND day <= toDate($__toTime)"
HOURS = (
    f"if({DAILY}, hour >= toStartOfDay($__fromTime) "
    "AND hour < toStartOfDay($__toTime) + INTERVAL 1 DAY, $__timeFilter(hour))"
)


def term_rows(columns: str, hourly: str, daily: str, group_by: str) -> str:
    """The selected terms' rows in the selected bucket, from term_hourly or term_daily."""
    return f"""
    SELECT {columns.format(bucket=hourly)}
    FROM term_hourly
    WHERE NOT {DAILY} AND $__timeFilter(hour) AND {TERMS} AND {SCOPE}
    GROUP BY {group_by}
    UNION ALL
    SELECT {columns.format(bucket=daily)}
    FROM term_daily
    WHERE {DAILY} AND {DAYS} AND {TERMS} AND {SCOPE}
    GROUP BY {group_by}"""


MENTIONS_PER_CHANNEL = term_rows(
    "{bucket} AS time, channel, term, sum(docs) AS docs",
    HOUR_BUCKET,
    DAY_BUCKET,
    "time, channel, term",
)

terms_dashboard = dashboard(
    "wgra-terms",
    "Term explorer",
    "How often terms are mentioned in a group or channels, relative to all comments and posts.",
    [
        panel(
            "timeseries",
            "Share of comments and posts mentioning the term (per 1,000)",
            f"""
WITH totals AS (
    SELECT {TOTAL_BUCKET} AS time, channel, sum(docs) AS n
    FROM scope_hourly
    WHERE {HOURS} AND {SCOPE}
    GROUP BY time, channel
)
SELECT t.time AS time, t.term AS term,
       if(${{rate:sqlstring}} = 'macro', 1000 * t.share_sum / s.members, 1000 * t.docs / s.n)
           AS per_1000
FROM (
    SELECT time, term, sum(c.docs) AS docs, sum(c.docs / totals.n) AS share_sum
    FROM ({MENTIONS_PER_CHANNEL}
    ) AS c
    INNER JOIN totals USING (time, channel)
    GROUP BY time, term
) AS t
INNER JOIN (SELECT time, sum(n) AS n, count() AS members FROM totals GROUP BY time) AS s
    USING time
ORDER BY time
""",
            0,
            0,
            24,
            11,
            description=(
                "Comments and posts that contain the term, per 1,000 comments and posts in the "
                "selected channels. Dividing by the total removes the daily and weekly activity "
                "swings, so the line shows the share of the conversation. Separate several terms "
                "with commas. Bucket: week sums whole ISO weeks (Monday to Sunday, UTC), as the "
                "long-term trends do; days and weeks reach back further than hours (180 days). "
                "Group rate: pooled divides all mentions by all comments and posts; macro "
                "averages each channel's share, so a big channel doesn't drown out the "
                "small ones (the long-term trends of groups use it)."
            ),
            interval="1h",
            series_label="term",
        ),
        panel(
            "timeseries",
            "Mentions",
            f"""
SELECT time, term, sum(docs) AS mentions
FROM ({MENTIONS_PER_CHANNEL}
)
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
SELECT * FROM ({
                term_rows(
                    "{bucket} AS time, term, uniqCombinedMerge(12)(authors) AS authors",
                    HOUR_BUCKET,
                    DAY_BUCKET,
                    "time, term",
                )
            }
)
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
SELECT t.term AS term, t.channel AS channel, t.docs AS mentions, t.authors AS authors,
       round(1000 * t.docs / s.docs, 2) AS per_1000
FROM (
    SELECT term, channel, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
    FROM ({
                term_rows(
                    "term, channel, sum(docs) AS docs, uniqCombinedMergeState(12)(authors) "
                    "AS authors",
                    "",
                    "",
                    "term, channel",
                )
            }
    )
    GROUP BY term, channel
) AS t
INNER JOIN (
    SELECT channel, sum(docs) AS docs
    FROM scope_hourly
    WHERE {HOURS} AND {SCOPE}
    GROUP BY channel
) AS s USING channel
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
SELECT created_at AS time, channel, doc_type AS type, substring(text, 1, 400) AS text,
       url AS link
FROM items
WHERE $__timeFilter(created_at) AND {SCOPE}
  AND ({TEXT_MATCHES_TERMS} OR hasAny(intents, {TERM_LIST}))
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
                                        "title": "Open",
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
                        "matcher": {"id": "byName", "options": "channel"},
                        "properties": [{"id": "custom.width", "value": 120}],
                    },
                    {
                        "matcher": {"id": "byName", "options": "type"},
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
        custom_variable("bucket", "Bucket", ["auto", "hour", "day", "week"], default="auto"),
        custom_variable("rate", "Group rate", ["pooled", "macro"], default="pooled"),
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
     WHERE channel IN ({BACKGROUND})
       AND hour >= now() - INTERVAL 8 DAY) AS n_background,
    -- how many comments' worth of weight the platform-wide share gets in "usual"
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
        WHERE channel IN ({BACKGROUND})
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
    b.mentions AS mentions_background,
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
                "before with its share in the platform's background, the r/all sample. Without "
                "history yet, the platform-wide share dominates, so this first shows what is "
                "distinctive for the group and turns into what is rising as history accumulates. "
                "Ignores the time picker. The real trend scoring is on the Trending now dashboard."
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

# the picked platforms: their polls, and their tracked channels (the group named like the
# platform, "reddit": every tracked subreddit, not r/all)
PLATFORMS = "platform IN (${platform:singlequote})"
TRACKED = (
    "channel IN (SELECT channel FROM channel_groups WHERE group_name IN (${platform:singlequote}))"
)
ingestion_dashboard = dashboard(
    "wgra-ingestion",
    "Ingestion",
    "Is the ingester healthy and complete?",
    [
        panel(
            "stat",
            "Comments + posts stored, last 24h",
            f"SELECT sum(docs) FROM scope_hourly "
            f"WHERE {TRACKED} AND hour >= now() - INTERVAL 24 HOUR",
            0,
            0,
            6,
            5,
            table=True,
            description="From the tracked channels of the selected platforms, without their "
            "samples (r/all).",
        ),
        panel(
            "stat",
            "Requests, last 10 minutes",
            f"SELECT count() FROM polls WHERE {PLATFORMS} AND ts > now() - INTERVAL 10 MINUTE",
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
            f"SELECT sum(gap) FROM polls WHERE {PLATFORMS} AND ts > now() - INTERVAL 24 HOUR",
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
            "WHERE platform = 'reddit' AND sample AND id_span > 0 AND $__timeFilter(ts)",
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
            f"""
SELECT $__timeInterval(ts) AS time, feed, sum(new_items) / ($__interval_s / 60) AS per_minute
FROM polls
WHERE {PLATFORMS} AND $__timeFilter(ts)
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
            f"""
SELECT $__timeInterval(ts) AS time,
       count() / ($__interval_s / 60) AS requests,
       countIf(status != 200) / ($__interval_s / 60) AS errors,
       sum(gap) / ($__interval_s / 60) AS gaps
FROM polls
WHERE {PLATFORMS} AND $__timeFilter(ts)
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
            f"""
SELECT platform, feed, count() AS polls, countIf(status != 200) AS errors,
       sum(new_items) AS new_items, sum(gap) AS gaps, round(avg(interval_s), 1) AS poll_every_s,
       round(argMax(rate, ts) * 60) AS items_per_minute, max(ts) AS last_poll
FROM polls
WHERE {PLATFORMS} AND ts > now() - INTERVAL 1 HOUR
GROUP BY platform, feed
ORDER BY platform, feed
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
            "Channels, last 24h",
            f"""
SELECT c.channel AS channel, c.platform AS platform, sum(s.docs) AS documents,
       arrayStringConcat(
           arraySort(groupArrayIf(concat(s.doc_type, ' ', toString(s.docs)), s.docs > 0)), ', '
       ) AS by_type,
       sum(s.authors) AS authors
FROM channels AS c
LEFT JOIN (
    SELECT channel, doc_type, sum(docs) AS docs, uniqCombinedMerge(12)(authors) AS authors
    FROM scope_hourly
    WHERE hour >= now() - INTERVAL 24 HOUR
    GROUP BY channel, doc_type
) AS s ON s.channel = c.channel
WHERE c.{PLATFORMS}
GROUP BY c.channel, c.platform
ORDER BY c.platform, documents DESC, c.channel
""",
            0,
            22,
            24,
            12,
            table=True,
            description="Every channel of config.yaml: the tracked ones, the samples (r/all) "
            "and the radar's search (r/_search). authors adds up per type: a person writing "
            "a comment and a post counts twice.",
        ),
    ],
    [
        query_variable(
            "platform",
            "Platform",
            "SELECT DISTINCT platform FROM channels ORDER BY platform",
            multi=True,
            include_all=True,
            all_value=None,
        ),
    ],
    "now-6h",
    refresh="1m",
)

# What the analyzer found (wgra analyze, every 15 minutes). A scope is a channel
# ("r/technology", "r/all") or a group ("tech"), the dashboard shows a group and its
# channels, or one channel.
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
    """SQL for the term explorer url of a trend, in its scope (a group or a channel, the
    scope picker takes either)."""
    return (
        "concat('/d/wgra-terms?var-terms=', encodeURLFormComponent(term), "
        f"'&var-group=', encodeURLFormComponent({scope}), '&from=now-7d&to=now')"
    )


# each trend's hourly mentions in the group in the week before the run, for the sparklines
SPARKLINES = f"""
WITH {LATEST_RUN}
SELECT hour AS time, term, sum(docs) AS mentions
FROM term_hourly
WHERE hour > latest_run - INTERVAL 7 DAY AND hour <= latest_run
  AND channel IN ({GROUP_CHANNELS})
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
            "share of the term on all of the platform (the r/all sample): what's distinctive, not "
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
                    "see docs/ARCHITECTURE.md §4.2), what trends are ranked by. times_usual: "
                    "the share of comments and posts mentioning the term in the window, divided "
                    "by its share in the 28 days before. new: barely mentioned before. breadth: "
                    "for a group, in how many of its channels the term trends, of those "
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
      AND channel IN ({GROUP_CHANNELS})
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
      AND channel IN ({GROUP_CHANNELS})
    GROUP BY time
) AS s USING time
ORDER BY time
""",
            0,
            18,
            24,
            10,
            description="The 8 strongest trends of the latest run, as a share of all comments "
            "and posts in the group's channels.",
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
        group_variable(),
        scopes_variable(),
        custom_variable("horizon", "Horizon", ["24h", "6h"], default="24h"),
        custom_variable(
            "kind",
            "Kind",
            ["word", "phrase", "domain", "subreddit", *INTENT_KINDS],
            default=["word", "phrase", "domain", "subreddit"],
            multi=True,
        ),
        custom_variable("subsumed", "Subsumed", ["hide", "show"], default="hide"),
    ],
    "now-7d",
    refresh="5m",
)


# What the long-term detector found (once a day, wgra analyze): per scope and window
# (13, 26, 52 weeks), the terms growing or fading steadily, of the latest analyzed week.
LATEST_WEEK = (
    "(SELECT max(week) FROM long_term_trends WHERE horizon = ${horizon:sqlstring}) AS latest"
)
LONG_TERM_ROWS = (
    "week = latest AND horizon = ${horizon:sqlstring} AND scope IN (${scope:singlequote}) "
    "AND kind IN (${kind:singlequote})"
)
# a trend's row: scopes can share terms (a group and its channels)
TREND_ID = "concat(scope, ' · ', term)"


def weekly_explore_url() -> str:
    """SQL for the term explorer url of a long-term trend: weekly, over its window."""
    return (
        "concat('/d/wgra-terms?var-terms=', encodeURLFormComponent(term), "
        "'&var-group=', encodeURLFormComponent(scope), "
        "'&var-bucket=week&var-rate=macro&from=', "
        "toString(toUnixTimestamp(toDateTime(window_start, 'UTC')) * 1000), '&to=now')"
    )


def long_term_table(category: str, title: str, y: int, description: str) -> dict:
    """The latest trends of one category, with each one's weekly share as a sparkline."""
    order = "change" if category == "one-off" else "growth"
    table = panel(
        "table",
        title,
        f"""
WITH {LATEST_WEEK}
SELECT
    {TREND_ID} AS id,
    scope,
    term,
    round(100 * (growth - 1), 1) AS per_month,
    q_value AS q,
    round(start_share, 3) AS start_per_1000,
    round(end_share, 3) AS end_per_1000,
    mentions,
    round(spike_share, 2) AS spike_share,
    round(peak, 1) AS peak,
    kind,
    {weekly_explore_url()} AS explore
FROM long_term_trends FINAL
WHERE {LONG_TERM_ROWS} AND category = '{category}'
ORDER BY abs(log({order})) DESC
LIMIT 100
""",
        0,
        y,
        24,
        10,
        table=True,
        description=description,
        fieldConfig={
            "defaults": {},
            "overrides": [
                link_to_explorer("term"),
                hidden("explore"),
                hidden("id"),
                width("scope", 170),
                width("per_month", 100),
                {
                    "matcher": {"id": "byName", "options": "per_month"},
                    "properties": [{"id": "unit", "value": "percent"}],
                },
                {
                    "matcher": {"id": "byName", "options": "q"},
                    "properties": [
                        {"id": "unit", "value": "sci"},
                        {"id": "decimals", "value": 1},
                        {"id": "custom.width", "value": 90},
                    ],
                },
                width("start_per_1000", 120),
                width("end_per_1000", 120),
                width("mentions", 90),
                width("spike_share", 100),
                width("peak", 70),
                width("kind", 70),
            ],
        },
    )
    # each trend's weekly share over its window, from the stored series
    table["targets"].append(
        {
            **target(
                f"""
WITH {LATEST_WEEK}
SELECT toDateTime(window_start, 'UTC') + toIntervalWeek(i - 1) AS time,
       {TREND_ID} AS id, weekly[i] AS per_1000
FROM long_term_trends FINAL
ARRAY JOIN arrayEnumerate(weekly) AS i
WHERE {LONG_TERM_ROWS} AND category = '{category}'
ORDER BY time
"""
            ),
            "refId": "B",
        }
    )
    columns = [
        "scope",
        "term",
        "per_month",
        "Trend #B",
        "q",
        "start_per_1000",
        "end_per_1000",
        "mentions",
        "spike_share",
        "peak",
        "kind",
        "explore",
        "id",
    ]
    table["transformations"] = [
        {"id": "timeSeriesTable", "options": {}},
        {"id": "joinByField", "options": {"byField": "id", "mode": "outerTabular"}},
        {
            "id": "organize",
            "options": {
                "renameByName": {
                    **{f"{column} A": column for column in columns},
                    "Trend #B": "weekly share",
                },
                "indexByName": {
                    name: index
                    for index, column in enumerate(columns)
                    for name in (column, f"{column} A")
                },
            },
        },
    ]
    table["fieldConfig"]["overrides"].append(
        {
            "matcher": {"id": "byName", "options": "weekly share"},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "sparkline", "hideValue": True}},
                {"id": "custom.width", "value": 200},
            ],
        }
    )
    descending = category != "fading"
    table["options"] = {"sortBy": [{"displayName": "per_month", "desc": descending}]}
    return table


LONG_TERM_COLUMNS_HELP = (
    "per_month: growth per month (Theil–Sen slope of the log weekly share, robust to "
    "one-off spikes). q: Mann–Kendall p-value after Benjamini–Hochberg over every term the "
    "run tested, at most 0.05. start/end_per_1000: the trend line at the first and last "
    "week of the window. spike_share: how much of the change comes from the two highest "
    "weeks. peak: the highest week, times the median week. A group's share is the average "
    "of its channels' shares. Click a term to open it in the term explorer, weekly."
)

long_term_dashboard = dashboard(
    "wgra-long-term",
    "Long-term trends",
    "Terms growing or fading steadily over 13, 26 or 52 weeks, found once a day by wgra analyze.",
    [
        panel(
            "stat",
            "Last run",
            "SELECT toUnixTimestamp(max(detected_at)) * 1000 FROM long_term_trends "
            "WHERE horizon = ${horizon:sqlstring}",
            0,
            0,
            6,
            4,
            table=True,
            unit="dateTimeFromNow",
            description="When the latest stored results were found. The detector runs every "
            "day after 00:30 UTC; the results only change when a week has completed.",
        ),
        panel(
            "stat",
            "Weeks analyzed up to",
            f"WITH {LATEST_WEEK} SELECT formatDateTime(latest - 1, '%a %e %b %Y')",
            6,
            0,
            6,
            4,
            table=True,
            description="The last day of the last complete week analyzed (weeks run Monday to "
            "Sunday, UTC). The current week isn't complete yet and is left out.",
            options={
                "colorMode": "none",
                "graphMode": "none",
                "textMode": "value",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False},
            },
        ),
        panel(
            "stat",
            "Weeks of history",
            f"""
SELECT greatest(max(intDiv(toMonday(today()) - first_week, 7)), 0)
FROM (
    SELECT if(toDayOfWeek(min(hour)) = 1, toMonday(min(hour)), toMonday(min(hour)) + 7)
           AS first_week
    FROM scope_hourly
    WHERE channel IN ({GROUP_CHANNELS})
    GROUP BY channel
)
""",
            12,
            0,
            6,
            4,
            table=True,
            description="Complete weeks of data in the group's channels. A window runs once "
            "it has that many weeks: 13, 26 or 52. Until then there's nothing here.",
        ),
        panel(
            "stat",
            "Trends",
            f"""
WITH {LATEST_WEEK}
SELECT countIf(category = 'emerging') AS emerging,
       countIf(category = 'mainstreaming') AS mainstreaming,
       countIf(category = 'fading') AS fading,
       countIf(category = 'one-off') AS `one-off`
FROM long_term_trends FINAL
WHERE {LONG_TERM_ROWS}
""",
            18,
            0,
            6,
            4,
            table=True,
            description="Stored trends in the selected scopes and window, at most 25 per scope "
            "and category.",
        ),
        long_term_table(
            "emerging",
            "Emerging: rare at the start of the window, growing steadily",
            4,
            "Terms mentioned by at most 1 in 1,000 comments and posts at the start of the window "
            "that grew significantly and steadily. " + LONG_TERM_COLUMNS_HELP,
        ),
        long_term_table(
            "mainstreaming",
            "Mainstreaming: common already, still growing",
            14,
            "Terms above 1 in 1,000 at the start of the window that kept growing significantly "
            "and steadily. " + LONG_TERM_COLUMNS_HELP,
        ),
        long_term_table(
            "fading",
            "Fading",
            24,
            "Terms whose share shrank significantly and steadily. " + LONG_TERM_COLUMNS_HELP,
        ),
        long_term_table(
            "one-off",
            "One-offs: the change is one event, not a trend",
            34,
            "Terms whose change between the first and second half of the window comes mostly "
            "from one or two weeks far above the rest (spike_share at least 0.5, peak at least "
            "3 times the median week). Sorted by that change. " + LONG_TERM_COLUMNS_HELP,
        ),
        panel(
            "timeseries",
            "The strongest trends, weekly share (per 1,000 comments and posts)",
            f"""
WITH {LATEST_WEEK}
SELECT toDateTime(window_start, 'UTC') + toIntervalWeek(i - 1) AS time,
       {TREND_ID} AS trend, weekly[i] AS per_1000
FROM long_term_trends FINAL
ARRAY JOIN arrayEnumerate(weekly) AS i
WHERE {LONG_TERM_ROWS} AND category IN ('emerging', 'mainstreaming', 'fading')
  AND ({TREND_ID}) IN (
      SELECT {TREND_ID} FROM long_term_trends FINAL
      WHERE {LONG_TERM_ROWS} AND category IN ('emerging', 'mainstreaming', 'fading')
      ORDER BY abs(log(growth)) DESC
      LIMIT 8
  )
ORDER BY time
""",
            0,
            44,
            24,
            10,
            description="The 8 fastest growing or fading terms in the selected scopes, as "
            "analyzed: weekly, a group's share the average of its channels'.",
            series_label="trend",
        ),
    ],
    [
        group_variable(),
        scopes_variable(),
        custom_variable("horizon", "Window", ["13w", "26w", "52w"], default="13w"),
        custom_variable(
            "kind",
            "Kind",
            ["word", "phrase", "domain", "subreddit", *INTENT_KINDS],
            default=["word", "phrase", "domain", "subreddit"],
            multi=True,
        ),
    ],
    "now-1y",
    refresh="1h",
)


# The lead–lag layer (wgra analyze, leadlag/): which channels pick up terms before
# others (edges, learned daily), and forecasts of which current bursts will reach which
# scopes, with how they turned out.
LATEST_EDGES = "day = (SELECT max(day) FROM propagation_edges)"
EDGE_ROWS = (
    f"{LATEST_EDGES} AND topic = ${{topic:sqlstring}} AND leader IN (${{leader:singlequote}})"
)
# a follower group measured without the leader, it's "the rest of" the group
FOLLOWER = "if(without_leader, concat(follower, ' (rest)'), follower)"
RESOLVED = "outcome IN ('hit', 'miss')"


def percent(*columns: str) -> dict:
    return {
        "matcher": {"id": "byRegexp", "options": "^(" + "|".join(columns) + ")$"},
        "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 0}],
    }


def hours_as_days(*columns: str) -> dict:
    return {
        "matcher": {"id": "byRegexp", "options": "^(" + "|".join(columns) + ")$"},
        "properties": [{"id": "unit", "value": "h"}, {"id": "decimals", "value": 0}],
    }


early_warning_dashboard = dashboard(
    "wgra-early-warning",
    "Early warning",
    "Which channels pick up terms before others, and forecasts of which current bursts "
    "will reach other channels, groups or all of reddit (r/all). Learned from at least 4–6 "
    "weeks of history.",
    [
        panel(
            "stat",
            "Edges learned",
            "SELECT toUnixTimestamp(max(computed_at)) * 1000 FROM propagation_edges",
            0,
            0,
            4,
            4,
            table=True,
            unit="dateTimeFromNow",
            description="When wgra analyze last learned the edges. It does once a day, after "
            "lead_lag.run_at (01:00 UTC).",
        ),
        panel(
            "stat",
            "Edges",
            f"SELECT count() FROM propagation_edges FINAL WHERE {LATEST_EDGES} "
            "AND topic = ${topic:sqlstring}",
            4,
            0,
            4,
            4,
            table=True,
            description="Leader -> follower pairs that pass the gates in the selected topic: "
            "at least 5 events and 3 hits, more hits than the base rate explains and the "
            "leader first in at least 70% of the events where both crossed (q-values of at "
            "most 0.05).",
        ),
        panel(
            "stat",
            "Events, closed",
            "SELECT count() AS events, countIf(closed) AS closed FROM lead_lag_events FINAL",
            8,
            0,
            4,
            4,
            table=True,
            description="Terms that trended somewhere, the unit edges are learned from. An "
            "event is closed when its span (3 days before its first trend to 14 days after) is "
            "over; only closed events count for base rates.",
        ),
        panel(
            "stat",
            "Pending forecasts",
            "SELECT count() FROM forecasts FINAL WHERE outcome = 'pending'",
            12,
            0,
            4,
            4,
            table=True,
        ),
        panel(
            "stat",
            "Forecasts that came true, 30 days",
            f"SELECT if(count() = 0, NULL, countIf(outcome = 'hit') / count()) "
            f"FROM forecasts FINAL WHERE {RESOLVED} AND created_at > now() - INTERVAL 30 DAY",
            16,
            0,
            4,
            4,
            table=True,
            unit="percentunit",
            description="Precision of the forecasts resolved in the last 30 days. "
            "`wgra replay --forecast` measures it on past data, with recall and calibration.",
        ),
        panel(
            "stat",
            "Forecast alerts, 24h",
            "SELECT count() FROM notifications WHERE kind = 'forecast' AND ok "
            "AND sent_at > now() - INTERVAL 24 HOUR",
            20,
            0,
            4,
            4,
            table=True,
            description="Forecast alerts are off by default (forecast.alert in config.yaml). "
            "They share the daily alert cap with trend alerts.",
        ),
        panel(
            "table",
            "Leader -> follower edges",
            f"""
SELECT
    leader,
    {FOLLOWER} AS follower,
    follower_type AS type,
    lag_median AS lead,
    concat(toString(round(lag_q25 / 24, 1)), '–', toString(round(lag_q75 / 24, 1)), 'd')
        AS lead_iqr,
    events AS n,
    hits,
    hit_rate,
    base_rate,
    probability,
    concat(toString(round(100 * probability_low)), '–',
           toString(round(100 * probability_high)), '%') AS interval,
    round(lift, 1) AS lift,
    lead_share AS first,
    greatest(q_value, direction_q) AS q,
    leader_onsets
FROM propagation_edges FINAL
WHERE {EDGE_ROWS}
ORDER BY lift DESC
LIMIT 500
""",
            0,
            4,
            24,
            11,
            table=True,
            description=(
                "Learned daily from the events of the last 180 days. lead: median time from the "
                "leader's onset (the first hour its last 24h crossed 2x its usual share, z 3) to "
                "the follower's, IQR in days. n: the leader's onsets the follower hadn't "
                "crossed before, with a known outcome. hit_rate: of those, followed within 7 "
                "days. base_rate: the share of all events in which the follower crossed at all. "
                "probability: the hit rate shrunk to the base rate by 4 pseudo-events, with its "
                "80% interval. lift: probability / base rate. first: of the events where both "
                "crossed within 7 days of each other, the share the leader was first in. q: the "
                "larger of two Benjamini–Hochberg q-values, the hits against the base rate "
                "(over all pairs) and the leader coming first against chance (over the "
                "associated pairs). '(rest)': a "
                "group of the leader's, without the leader's own mentions. Edges need 4–6 weeks "
                "of history to mean anything."
            ),
            fieldConfig={
                "defaults": {},
                "overrides": [
                    hours_as_days("lead"),
                    percent("hit_rate", "base_rate", "probability", "first"),
                    {
                        "matcher": {"id": "byName", "options": "q"},
                        "properties": [
                            {"id": "unit", "value": "sci"},
                            {"id": "decimals", "value": 1},
                        ],
                    },
                    width("leader", 170),
                    width("follower", 190),
                    width("type", 90),
                    width("n", 60),
                    width("hits", 60),
                ],
            },
            options={"sortBy": [{"displayName": "lift", "desc": True}]},
        ),
        panel(
            "nodeGraph",
            "Who leads whom",
            f"""
SELECT scope AS id, scope AS title, toFloat64(count()) AS mainstat
FROM (
    SELECT leader AS scope FROM propagation_edges FINAL WHERE {EDGE_ROWS}
    UNION ALL
    SELECT {FOLLOWER} FROM propagation_edges FINAL WHERE {EDGE_ROWS}
)
GROUP BY scope
""",
            0,
            15,
            12,
            12,
            table=True,
            description="The edges of the table above as a graph: arrows from leaders to "
            "followers, labeled with the median lead in days and the lift. A node's number is "
            "the edges it's part of.",
        ),
        panel(
            "table",
            "Recent cascades",
            """
SELECT
    term,
    start AS first_trend,
    topic,
    arrayStringConcat(
        arrayMap(o -> concat(o.1, ' ', formatDateTime(o.3, '%d %b %H:00')),
                 arraySort(o -> o.3, arrayFilter(o -> o.2 = '', onsets))),
        ' → ') AS cascade,
    length(arrayFilter(o -> o.2 = '', onsets)) AS reached,
    closed
FROM lead_lag_events FINAL
WHERE start > now() - INTERVAL 14 DAY AND length(onsets) > 1
ORDER BY start DESC
LIMIT 200
""",
            12,
            15,
            12,
            12,
            table=True,
            description="Events of the last 14 days that reached more than one scope, with every "
            "scope's onset in the order they crossed (UTC). This is what the edges are learned "
            "from. reached: the scopes that crossed.",
            fieldConfig={
                "defaults": {},
                "overrides": [width("term", 140), width("first_trend", 160), width("topic", 90)],
            },
        ),
        panel(
            "table",
            "Current forecasts",
            f"""
SELECT
    term,
    leader,
    if(without_leader, concat(follower, ' (rest)'), follower) AS follower,
    probability AS chance,
    concat(toString(round(100 * probability_low)), '–',
           toString(round(100 * probability_high)), '%') AS interval,
    base_rate,
    expected_at,
    due_by,
    leader_onset,
    created_at,
    edge_events AS n,
    round(lift, 1) AS lift,
    alert,
    {explore_url("leader")} AS explore
FROM forecasts FINAL
WHERE outcome = 'pending'
ORDER BY probability DESC
LIMIT 200
""",
            0,
            27,
            24,
            9,
            table=True,
            description="A term rising in a leader that the follower hasn't picked up yet: the "
            "chance it will within 7 days of the leader's onset (the edge's probability, "
            "lowered for the time that already passed), against the follower's base rate, and "
            "when it's expected (the leader's onset plus the edge's median lead). Click a term "
            "to see it in the leader.",
            fieldConfig={
                "defaults": {},
                "overrides": [
                    link_to_explorer("term"),
                    hidden("explore"),
                    percent("chance", "base_rate"),
                    width("term", 160),
                    width("leader", 160),
                    width("follower", 170),
                ],
            },
        ),
        panel(
            "table",
            "Track record, last 30 days",
            f"""
SELECT
    created_at,
    term,
    leader,
    if(without_leader, concat(follower, ' (rest)'), follower) AS follower,
    probability AS chance,
    outcome,
    dateDiff('hour', created_at, follower_onset) AS warning,
    dateDiff('hour', leader_onset, follower_onset) AS lag,
    round(lag_median) AS expected_lag,
    {explore_url("follower")} AS explore
FROM forecasts FINAL
WHERE {RESOLVED} AND created_at > now() - INTERVAL 30 DAY
ORDER BY created_at DESC
LIMIT 500
""",
            0,
            36,
            14,
            10,
            table=True,
            description="Resolved forecasts: hit when the follower crossed by the due time, "
            "miss otherwise. warning: hours from the forecast to the follower's onset. lag: from "
            "the leader's onset to the follower's, against the lag the edge expected.",
            fieldConfig={
                "defaults": {},
                "overrides": [
                    link_to_explorer("term"),
                    hidden("explore"),
                    percent("chance"),
                    hours_as_days("warning", "lag", "expected_lag"),
                    width("created_at", 160),
                ],
            },
        ),
        panel(
            "table",
            "Calibration, last 90 days",
            f"""
SELECT
    toUInt8(floor(least(probability, 0.999) * 5)) AS bin,
    concat(toString(bin * 20), '–', toString(bin * 20 + 20), '%') AS predicted_bin,
    count() AS forecasts,
    avg(probability) AS predicted,
    countIf(outcome = 'hit') / count() AS came_true,
    avg(base_rate) AS base_rate
FROM forecasts FINAL
WHERE {RESOLVED} AND created_at > now() - INTERVAL 90 DAY
GROUP BY bin
ORDER BY bin
""",
            14,
            36,
            10,
            10,
            table=True,
            description="Well calibrated forecasts come true about as often as they say. The "
            "base rate column is what always forecasting the follower's usual rate would say.",
            fieldConfig={
                "defaults": {},
                "overrides": [percent("predicted", "came_true", "base_rate"), hidden("bin")],
            },
        ),
        panel(
            "timeseries",
            "Forecasts per day, and how many came true",
            """
SELECT toStartOfDay(created_at) AS time,
       countIf(outcome = 'hit') AS came_true,
       countIf(outcome = 'miss') AS missed,
       countIf(outcome = 'pending') AS pending
FROM forecasts FINAL
WHERE $__timeFilter(created_at)
GROUP BY time
ORDER BY time
""",
            0,
            46,
            14,
            8,
            draw_style="bars",
            stacking="normal",
        ),
        panel(
            "table",
            "Onsets vs Wikipedia (optional)",
            """
SELECT
    count() AS events,
    countIf(wiki_onset IS NOT NULL) AS with_interest,
    countIf(lead_days > 0) AS onset_first,
    countIf(lead_days = 0) AS same_day,
    countIf(lead_days < 0) AS wikipedia_first,
    quantileExactIf(0.5)(lead_days, lead_days IS NOT NULL) AS median_lead_days
FROM wiki_leads FINAL
WHERE start > now() - INTERVAL 90 DAY
""",
            14,
            46,
            10,
            8,
            table=True,
            description="With wikipedia.enabled: for events whose term names a Wikipedia "
            "article, did daily pageviews rise (3x their 28-day median, at least 100) after "
            "the term's first onset? `wgra wikipedia` prints a sign test.",
        ),
    ],
    [
        query_variable(
            "topic",
            "Topic",
            "SELECT DISTINCT topic FROM propagation_edges "
            "WHERE day = (SELECT max(day) FROM propagation_edges) "
            "ORDER BY topic = 'all' DESC, topic",
            default="all",
        ),
        query_variable(
            "leader",
            "Leaders",
            "SELECT DISTINCT leader FROM propagation_edges "
            "WHERE day = (SELECT max(day) FROM propagation_edges) ORDER BY leader",
            multi=True,
            include_all=True,
            all_value=None,
        ),
    ],
    "now-30d",
    refresh="5m",
)
# the node graph's second frame: the edges, from leader to follower
next(p for p in early_warning_dashboard["panels"] if p["type"] == "nodeGraph")["targets"].append(
    {
        **target(
            f"""
SELECT concat(leader, ' -> ', {FOLLOWER}) AS id, leader AS source, {FOLLOWER} AS target,
       concat(toString(round(lag_median / 24, 1)), 'd') AS mainstat,
       concat('lift ', toString(round(lift, 1))) AS secondarystat
FROM propagation_edges FINAL
WHERE {EDGE_ROWS}
""",
            table=True,
        ),
        "refId": "B",
    }
)


# Intents (docs/ARCHITECTURE.md §4.7): why people mention things. Switches are stored as
# "x → y", the other kinds as "alternative: x", "complaint: x" and "need: x".
# what an intent is about, without its kind
ENTITY = "if(position(term, ': ') > 0, substring(term, position(term, ': ') + 2), term)"
INTENT_DAYS = "day >= toDate($__fromTime) AND day <= toDate($__toTime)"
# the same whole days, for scope_hourly
INTENT_HOURS = (
    "hour >= toDateTime(toDate($__fromTime), 'UTC') "
    "AND hour < toDateTime(toDate($__toTime) + 1, 'UTC')"
)


def intent_links(group: str = "${group:sqlstring}") -> str:
    """SQL for the urls of an intent: its comments on this dashboard, and the explorer."""
    return (
        "concat('/d/wgra-intents?var-term=', encodeURLFormComponent(term), "
        f"'&var-group=', encodeURLFormComponent({group}), '&from=now-30d&to=now') AS examples, "
        "concat('/d/wgra-terms?var-terms=', encodeURLFormComponent(term), "
        f"'&var-group=', encodeURLFormComponent({group}), "
        "'&var-bucket=day&from=now-90d&to=now') AS explore"
    )


def link_to_examples(column: str) -> dict:
    """A table override: clicking `column` shows the comments behind the intent (url in
    "examples"), or opens it in the term explorer."""
    return {
        "matcher": {"id": "byName", "options": column},
        "properties": [
            {
                "id": "links",
                "value": [
                    {"title": "Comments of the last 48 hours", "url": "${__data.fields.examples}"},
                    {"title": "Open in the term explorer", "url": "${__data.fields.explore}"},
                ],
            }
        ],
    }


def with_daily_sparklines(
    table_panel: dict, kind: str, columns: list[str], days: str, pixels: int = 200
) -> dict:
    """Adds each term's mentions per day as a sparkline column ("per day")."""
    table_panel["targets"].append(
        {
            **target(
                f"""
SELECT toDateTime(day, 'UTC') AS time, term, sum(docs) AS mentions
FROM term_daily
WHERE {SCOPE} AND kind = '{kind}' AND {days}
GROUP BY time, term
ORDER BY time
"""
            ),
            "refId": "B",
        }
    )
    table_panel["transformations"] = [
        {"id": "timeSeriesTable", "options": {}},
        {"id": "joinByField", "options": {"byField": "term", "mode": "outerTabular"}},
        # terms that are only in the sparklines (not in the table's top) are dropped
        {
            "id": "filterByValue",
            "options": {
                "type": "exclude",
                "match": "any",
                "filters": [{"fieldName": "mentions A", "config": {"id": "isNull"}}],
            },
        },
        {
            "id": "organize",
            "options": {
                "renameByName": {
                    **{f"{column} A": column for column in columns},
                    "Trend #B": "per day",
                },
                "indexByName": {
                    name: index
                    for index, column in enumerate(columns)
                    for name in (column, f"{column} A")
                },
            },
        },
    ]
    table_panel["fieldConfig"]["overrides"].append(
        {
            "matcher": {"id": "byName", "options": "per day"},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "sparkline", "hideValue": True}},
                {"id": "custom.width", "value": pixels},
            ],
        }
    )
    return table_panel


SWITCH_COLUMNS = [
    "from",
    "to",
    "mentions",
    "authors",
    "the other way",
    "Trend #B",
    "per_10k",
    "term",
    "examples",
    "explore",
]
switches_table = with_daily_sparklines(
    panel(
        "table",
        "Top switching flows (x → y)",
        f"""
WITH
    (SELECT sum(docs) FROM scope_hourly WHERE {SCOPE} AND {INTENT_HOURS}) AS total,
    flows AS (
        SELECT term, sum(docs) AS mentions, uniqCombinedMerge(12)(authors) AS authors
        FROM term_daily
        WHERE {SCOPE} AND kind = 'switch' AND {INTENT_DAYS}
        GROUP BY term
    )
SELECT
    splitByString(' → ', f.term)[1] AS from,
    splitByString(' → ', f.term)[2] AS to,
    f.mentions AS mentions,
    f.authors AS authors,
    r.mentions AS `the other way`,
    round(10000 * f.mentions / total, 2) AS per_10k,
    f.term AS term,
    {intent_links()}
FROM flows AS f
LEFT JOIN flows AS r
    ON r.term = concat(splitByString(' → ', f.term)[2], ' → ', splitByString(' → ', f.term)[1])
WHERE f.authors >= ${{min_authors:raw}}
ORDER BY mentions DESC, authors DESC, from
LIMIT 50
""",
        0,
        5,
        24,
        11,
        table=True,
        description=(
            "Someone switched from x to y, in the selected channels and time range: "
            "'switched from Notion to Obsidian', 'dropped ChatGPT for Claude', 'we replaced our "
            "Jira with Linear', 'the Jenkins to GitHub Actions migration'. mentions: comments "
            "and posts (each counts once), authors: different people. the other way: the "
            "mentions of y → x, who is winning. per_10k: per 10,000 comments and posts. Click a "
            "flow for the comments behind it (last 48 hours) or the term explorer."
        ),
        fieldConfig={
            "defaults": {},
            "overrides": [
                link_to_examples("from"),
                link_to_examples("to"),
                hidden("term"),
                hidden("examples"),
                hidden("explore"),
                width("mentions", 90),
                width("authors", 80),
                width("the other way", 110),
                width("per_10k", 80),
            ],
        },
    ),
    "switch",
    SWITCH_COLUMNS,
    INTENT_DAYS,
)
switches_table["options"] = {"sortBy": [{"displayName": "mentions", "desc": True}]}

RISING_COLUMNS = [
    "entity",
    "mentions",
    "Trend #B",
    "excess",
    "times_usual",
    "per_week_before",
    "authors",
    "trend_z",
    "term",
    "examples",
    "explore",
]
RISING_DAYS = "day >= today() - 34"


def rising_table(kind: str, title: str, x: int, description: str, y: int = 16) -> dict:
    """The last 7 days against the 28 before, the most extra mentions first."""
    table = with_daily_sparklines(
        panel(
            "table",
            title,
            f"""
WITH
    (SELECT sum(docs) FROM scope_hourly
     WHERE {SCOPE} AND hour >= toDateTime(today() - 6, 'UTC')) AS n_now,
    (SELECT sum(docs) FROM scope_hourly
     WHERE {SCOPE} AND hour >= toDateTime(today() - 34, 'UTC')
       AND hour < toDateTime(today() - 6, 'UTC')) AS n_before,
    trending AS (
        SELECT term, max(z) AS z FROM trends
        WHERE detected_at > now() - INTERVAL 24 HOUR AND kind = '{kind}' AND subsumed_by = ''
          AND scope IN (SELECT ${{group:sqlstring}} UNION ALL {GROUP_CHANNELS})
        GROUP BY term
    )
SELECT
    {ENTITY} AS entity,
    sumIf(docs, day >= today() - 6) AS mentions,
    uniqCombinedMergeIf(12)(authors, day >= today() - 6) AS authors,
    round(sumIf(docs, day < today() - 6) / 4, 1) AS per_week_before,
    -- the share now against the share before, with half a mention added to both
    round((mentions + 0.5) / n_now / ((sumIf(docs, day < today() - 6) + 0.5)
          / greatest(n_before, 1)), 1) AS times_usual,
    round(mentions - sumIf(docs, day < today() - 6) * n_now / greatest(n_before, 1), 1)
        AS excess,
    round(any(t.z), 1) AS trend_z,
    term,
    {intent_links()}
FROM term_daily
LEFT JOIN trending AS t USING term
WHERE {SCOPE} AND kind = '{kind}' AND {RISING_DAYS}
GROUP BY term
HAVING mentions >= ${{min_mentions:raw}} AND authors >= ${{min_authors:raw}}
ORDER BY excess DESC, mentions DESC
LIMIT 30
""",
            x,
            y,
            12,
            11,
            table=True,
            description=description,
            fieldConfig={
                "defaults": {},
                "overrides": [
                    link_to_examples("entity"),
                    hidden("term"),
                    hidden("examples"),
                    hidden("explore"),
                    width("mentions", 80),
                    width("excess", 65),
                    width("times_usual", 90),
                    width("per_week_before", 115),
                    width("authors", 70),
                    width("trend_z", 65),
                ],
            },
        ),
        kind,
        RISING_COLUMNS,
        RISING_DAYS,
        pixels=130,
    )
    table["options"] = {"sortBy": [{"displayName": "excess", "desc": True}]}
    return table


RISING_HELP = (
    "The last 7 days (today included) against the 28 days before, in the selected channels; "
    "ignores the time picker. mentions, authors: the last 7 days. per_week_before: the weekly "
    "average of the 28 days before. times_usual: the share of comments and posts now against "
    "before. excess: mentions above what the share before would give, what the table is "
    "sorted by. trend_z: the strongest score of the short-term detector in the last 24 "
    "hours, if it trends in the group or one of its channels. per day: the last 35 days. "
    "Click an entry for the comments behind it."
)

needs_table = panel(
    "table",
    "Top unmet needs per group",
    f"""
SELECT
    g.group_name AS group,
    substring(t.term, 7) AS need,
    sum(t.docs) AS mentions,
    uniqCombinedMerge(12)(t.authors) AS authors,
    t.term AS term,
    {intent_links("group")}
FROM term_daily AS t
INNER JOIN (
    SELECT group_name, channel FROM channel_groups
    WHERE group_name NOT IN (SELECT platform FROM channels)
    UNION ALL SELECT channel, channel FROM channels WHERE background
) AS g ON g.channel = t.channel
WHERE t.kind = 'need' AND {INTENT_DAYS.replace("day", "t.day")}
  AND $__conditionalAll(t.doc_type IN (${{doc_type:singlequote}}), $doc_type)
GROUP BY group, term
HAVING authors >= ${{min_authors:raw}}
ORDER BY group, mentions DESC, authors DESC, need
LIMIT 10 BY group
""",
    0,
    27,
    10,
    12,
    table=True,
    description=(
        "The 10 needs mentioned most in each configured group (and the r/all sample) in the "
        "time range: 'is there an app to …', 'I wish there was a way to …', 'I'd pay for an "
        "app that …', 'does anyone know a tool for …'. A need is the 2–3 words after it "
        "('track my sleep'). Ignores the group picker. Click a need for its comments."
    ),
    fieldConfig={
        "defaults": {},
        "overrides": [
            link_to_examples("need"),
            hidden("term"),
            hidden("examples"),
            hidden("explore"),
            width("group", 90),
            width("mentions", 85),
            width("authors", 75),
        ],
    },
)

# the kind of an intent's term: a switch has no kind in front ("notion → obsidian"), the
# others do ("considering: notion → obsidian"), and no entity has a colon
TERM_KIND = "if(position(t, ': ') > 0, splitByString(': ', t)[1], 'switch')"
examples_table = panel(
    "table",
    "Comments behind intents, last 48 hours",
    f"""
SELECT
    created_at AS time,
    channel,
    arrayStringConcat(arrayFilter(t -> {TERM_KIND} IN (${{intent_kind:singlequote}})
                                       AND (${{term:sqlstring}} = '' OR t = ${{term:sqlstring}}),
                                  intents), ', ') AS found,
    substring(text, 1, 500) AS text,
    url AS link
FROM items
WHERE {SCOPE} AND created_at > now() - INTERVAL 48 HOUR
  AND arrayExists(t -> {TERM_KIND} IN (${{intent_kind:singlequote}})
                       AND (${{term:sqlstring}} = '' OR t = ${{term:sqlstring}}), intents)
ORDER BY created_at DESC
LIMIT 200
""",
    10,
    27,
    14,
    12,
    table=True,
    description=(
        "The comments and posts the intents were found in, newest first. Raw text is only kept "
        "for 48 hours. Set Term (or click an entry in the tables above) to see one intent's "
        "comments, e.g. 'notion → obsidian' or 'complaint: reddit'; empty shows all of the "
        "selected kinds."
    ),
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
                                "title": "Open",
                                "url": "${__value.raw}",
                                "targetBlank": True,
                            }
                        ],
                    },
                    {"id": "custom.width", "value": 90},
                ],
            },
            width("time", 160),
            width("channel", 120),
            width("found", 220),
        ],
    },
)


def text_stat(title: str, sql: str, x: int, y: int, w: int, h: int, description: str) -> dict:
    """A stat panel showing a text value, such as a date."""
    stat = panel("stat", title, sql, x, y, w, h, table=True, description=description)
    stat["options"]["reduceOptions"]["fields"] = "/.*/"
    return stat


def intent_count(kind: str, title: str, x: int) -> dict:
    return panel(
        "stat",
        title,
        f"SELECT sum(docs) FROM term_daily WHERE {SCOPE} AND kind = '{kind}' AND {INTENT_DAYS}",
        x,
        0,
        4,
        5,
        table=True,
        description=f"Comments and posts with a {kind} intent in the time range.",
    )


intent_dashboard = dashboard(
    "wgra-intents",
    "Intent radar",
    "Why people mention things: switches between products, switches considered, "
    "alternatives sought, complaints and unmet needs.",
    [
        intent_count("switch", "Switches", 0),
        intent_count("considering", "Considering a switch", 4),
        intent_count("alternative", "Alternatives sought", 8),
        intent_count("complaint", "Complaints", 12),
        intent_count("need", "Needs", 16),
        text_stat(
            "Counting intents since",
            f"SELECT toString(min(day)) FROM term_daily WHERE kind IN ({INTENT_KIND_LIST})",
            20,
            0,
            4,
            5,
            description="The first day with intents, in any channel: they're extracted at "
            "ingest, so there is no history before the ingester started extracting them (plus "
            "the 48 hours of raw text before, with wgra backfill-intents).",
        ),
        switches_table,
        rising_table(
            "alternative",
            "Rising: alternatives sought",
            0,
            "Alternatives people look for or use instead: 'alternatives to LastPass', 'a good "
            "Plex alternative', 'I use Firefox instead of Chrome', 'moving away from AWS'. "
            + RISING_HELP,
        ),
        rising_table(
            "complaint",
            "Rising: complaints",
            12,
            "'is Reddit down?', 'Teams is unusable', 'cancelled my Netflix subscription', "
            "'Spotify raised prices again', 'YouTube enshittification'. " + RISING_HELP,
        ),
        needs_table,
        examples_table,
        rising_table(
            "considering",
            "Rising: switches considered",
            0,
            "Someone thinks of switching from x to y ('x → y') or of leaving x ('x'), in the "
            "first person: 'I'm thinking of switching from Notion to Obsidian', 'should I ditch "
            "Notion?', 'about to cancel Netflix'. Not after if, would or could, not advice "
            "('you could switch'). " + RISING_HELP,
            y=39,
        ),
        panel(
            "timeseries",
            "Intents per day",
            f"""
SELECT toDateTime(day, 'UTC') AS time, kind, sum(docs) AS mentions
FROM term_daily
WHERE {SCOPE} AND kind IN ({INTENT_KIND_LIST}) AND {INTENT_DAYS}
GROUP BY time, kind
ORDER BY time
""",
            12,
            39,
            12,
            11,
            description="Comments and posts with an intent per day, by kind.",
            series_label="kind",
            draw_style="bars",
            stacking="normal",
        ),
    ],
    [
        *scope_variables(),
        custom_variable("min_authors", "Min authors", ["1", "2", "3", "5", "10"], default="1"),
        custom_variable(
            "min_mentions", "Min mentions (7 days)", ["1", "2", "3", "5", "10"], default="2"
        ),
        {
            "type": "textbox",
            "name": "term",
            "label": "Term (comments)",
            "query": "",
            "current": {"text": "", "value": ""},
        },
        custom_variable(
            "intent_kind",
            "Kinds (comments)",
            INTENT_KINDS,
            default=INTENT_KINDS,
            multi=True,
        ),
    ],
    "now-30d",
    refresh="15m",
)

OUT.mkdir(parents=True, exist_ok=True)
for name, board in [
    ("trending", trending_dashboard),
    ("intents", intent_dashboard),
    ("long-term", long_term_dashboard),
    ("early-warning", early_warning_dashboard),
    ("term-explorer", terms_dashboard),
    ("rising", rising_dashboard),
    ("ingestion", ingestion_dashboard),
]:
    (OUT / f"{name}.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n")
    print("wrote", OUT / f"{name}.json")
