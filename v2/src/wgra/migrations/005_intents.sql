-- Intents (docs/ARCHITECTURE-V2.md §4.7): switches, alternatives, complaints and needs are
-- counted in term_events, term_hourly and term_daily like words, under kinds of their own
-- ("switch", "alternative", "complaint", "need") and terms no word can have ("notion →
-- obsidian", "complaint: netflix"). No new tables.
--
-- The raw items remember which intents they carry, so dashboards can show the comments
-- behind an intent exactly. Like the text, this is gone after 48 hours. Items stored before
-- this migration, or by an ingester that predates it, have none.
ALTER TABLE items ADD COLUMN IF NOT EXISTS intents Array(String) DEFAULT [] AFTER token_count;
