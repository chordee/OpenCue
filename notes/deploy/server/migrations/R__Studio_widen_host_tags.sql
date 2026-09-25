-- Studio change, not part of upstream OpenCue.
--
-- host.str_tags holds every tag of a host joined with spaces, and upstream
-- limits it to 128 characters. A render node that lists several DCC versions in
-- RQD_TAGS goes over the limit, and its registration fails inside Cuebot with
-- "value too long for type character varying(128)" while RQD reports nothing.
-- See notes/sandbox/32.
--
-- Repeatable migration: Flyway runs it after the versioned ones, and again only
-- when this file changes, so it survives upstream migrations being added.

ALTER TABLE host ALTER COLUMN str_tags TYPE VARCHAR(4000);

CREATE OR REPLACE FUNCTION recalculate_tags(IN VARCHAR)
RETURNS VOID AS $body$
DECLARE
    str_host_id ALIAS FOR $1;

    tag RECORD;
    full_str_tag VARCHAR(4000) := '';
BEGIN
  --
  -- concatenates all tags in host_tag and sets host.str_tags
  --
  FOR tag IN (SELECT str_tag FROM host_tag WHERE pk_host=str_host_id ORDER BY str_tag_type ASC, str_tag ASC) LOOP
    full_str_tag := full_str_tag || ' ' || tag.str_tag;
  END LOOP;

  EXECUTE 'UPDATE host SET str_tags=trim($1) WHERE pk_host=$2'
    USING full_str_tag, str_host_id;
END;
$body$
LANGUAGE PLPGSQL;
