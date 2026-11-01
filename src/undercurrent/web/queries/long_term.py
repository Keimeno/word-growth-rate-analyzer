"""Long-term trends: once a day, per scope and window (13, 26, 52 weeks), the terms growing
or fading steadily, of the latest analyzed week."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from undercurrent.web.models import LongTerm, LongTermTrend
from undercurrent.web.queries import GROUP_CHANNELS, NOW, TODAY, TREND_SCOPES, WORD_KINDS, Db, Items
from undercurrent.web.queries import ScopeQuery as _ScopeQuery


class LongTermQuery(_ScopeQuery):
    horizon: Literal["13w", "26w", "52w"] = "13w"
    kinds: Items = Field(WORD_KINDS)


LATEST_WEEK = (
    "(SELECT maxOrNull(week) FROM long_term_trends "
    f"WHERE horizon = {{horizon:String}} AND detected_at <= {NOW}) AS latest"
)
LONG_TERM_ROWS = (
    f"week = latest AND horizon = {{horizon:String}} AND {TREND_SCOPES} "
    "AND has({kinds:Array(String)}, kind)"
)


def long_term(db: Db, query: LongTermQuery) -> LongTerm:
    parameters = {**query.parameters(), "horizon": query.horizon, "kinds": query.kinds}
    status = db.one(
        f"""
        WITH {LATEST_WEEK}
        SELECT
            (SELECT maxOrNull(detected_at) FROM long_term_trends
             WHERE horizon = {{horizon:String}} AND detected_at <= {NOW}) AS last_run,
            latest - 1 AS analyzed_until,
            (SELECT greatest(max(intDiv(toMonday({TODAY}) - first_week, 7)), 0)
             FROM (
                 SELECT if(toDayOfWeek(min(hour)) = 1, toMonday(min(hour)),
                           toMonday(min(hour)) + 7) AS first_week
                 FROM scope_hourly
                 WHERE channel IN ({GROUP_CHANNELS})
                 GROUP BY channel
             )) AS weeks_of_history
        """,
        parameters,
    )
    rows = db.rows(
        f"""
        WITH {LATEST_WEEK}
        SELECT scope, term, kind, category, growth, q_value AS q, start_share, end_share,
               mentions, spike_share, peak, change, window_start, weekly
        FROM long_term_trends FINAL
        WHERE {LONG_TERM_ROWS}
        ORDER BY category, abs(log(if(category = 'one-off', change, growth))) DESC
        LIMIT 100 BY category
        """,
        parameters,
    )
    return LongTerm(**status, trends=[LongTermTrend.model_validate(row) for row in rows])
