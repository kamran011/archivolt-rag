-- Summary + buffer chat memory: older turns are folded into a running summary while the
-- most recent turns are sent verbatim. Matches backend/app/models/conversation.py.

ALTER TABLE conversations ADD COLUMN history_summary text;
ALTER TABLE conversations ADD COLUMN summarized_message_count integer NOT NULL DEFAULT 0;
