UPDATE operation_log
SET details = CASE
    WHEN NOT json_valid(details) THEN json_object()
    WHEN operation = 'remember' THEN
        json_patch(
            json_patch(
                CASE WHEN json_type(details, '$.core') IN ('true', 'false')
                    THEN json_object('core', json(json_type(details, '$.core')))
                    ELSE json_object() END,
                CASE WHEN json_type(details, '$.genome') IN ('true', 'false')
                    THEN json_object('genome', json(json_type(details, '$.genome')))
                    ELSE json_object() END
            ),
            CASE WHEN json_type(details, '$.work') IN ('true', 'false')
                THEN json_object('work', json(json_type(details, '$.work')))
                ELSE json_object() END
        )
    WHEN operation = 'instinct_feedback' THEN
        CASE WHEN json_type(details, '$.followed') IN ('true', 'false')
            THEN json_object('followed', json(json_type(details, '$.followed')))
            ELSE json_object() END
    WHEN operation = 'mark_core' THEN
        CASE WHEN json_type(details, '$.tier') IN ('integer', 'real')
                AND json_extract(details, '$.tier') BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
            THEN json_object('tier', json_extract(details, '$.tier'))
            ELSE json_object() END
    WHEN operation = 'assessment_report' THEN
        CASE WHEN json_type(details, '$.function_score') IN ('integer', 'real')
                AND json_extract(details, '$.function_score') BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
            THEN json_object('function_score', json_extract(details, '$.function_score'))
            ELSE json_object() END
    WHEN operation = 'reindex' THEN
        CASE WHEN json_type(details, '$.full') IN ('true', 'false')
            THEN json_object('full', json(json_type(details, '$.full')))
            ELSE json_object() END
    WHEN operation = 'graph_view' THEN
        CASE WHEN json_type(details, '$.depth') IN ('integer', 'real')
                AND json_extract(details, '$.depth') BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
            THEN json_object('depth', json_extract(details, '$.depth'))
            ELSE json_object() END
    WHEN operation = 'clipboard_pin' THEN
        CASE WHEN json_type(details, '$.priority') IN ('integer', 'real')
                AND json_extract(details, '$.priority') BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
            THEN json_object('priority', json_extract(details, '$.priority'))
            ELSE json_object() END
    WHEN operation = 'clipboard_remind' THEN
        json_patch(
            json_patch(
                CASE WHEN json_type(details, '$.value') IN ('integer', 'real')
                        AND json_extract(details, '$.value') BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308
                    THEN json_object('value', json_extract(details, '$.value'))
                    ELSE json_object() END,
                CASE WHEN json_type(details, '$.repeat') IN ('true', 'false')
                    THEN json_object('repeat', json(json_type(details, '$.repeat')))
                    ELSE json_object() END
            ),
            CASE WHEN json_type(details, '$.trigger') = 'text'
                    AND json_extract(details, '$.trigger') IN ('every_n_steps', 'interval_seconds', 'once_at')
                THEN json_object('trigger', json_extract(details, '$.trigger'))
                ELSE json_object() END
        )
    WHEN operation = 'reflect' THEN
        CASE WHEN json_type(details, '$.focus') = 'text'
                AND json_extract(details, '$.focus') IN (
                    'usage', 'gaps', 'instincts', 'contradictions',
                    'vital_signs', 'staleness', 'instinct_contexts',
                    'classifications', 'resonances', 'instinct_clusters',
                    'coherence', 'anchors', 'assessments', 'fidelity',
                    'cohesion', 'persistence'
                )
            THEN json_object('focus', json_extract(details, '$.focus'))
            ELSE json_object() END
    WHEN operation = 'jot' THEN
        json_patch(
            CASE WHEN json_type(details, '$.scope') = 'text'
                    AND json_extract(details, '$.scope') IN ('project', 'global')
                THEN json_object('scope', json_extract(details, '$.scope'))
                ELSE json_object() END,
            CASE WHEN json_type(details, '$.status') = 'text'
                    AND json_extract(details, '$.status') IN ('open', 'deferred', 'done')
                THEN json_object('status', json_extract(details, '$.status'))
                ELSE json_object() END
        )
    WHEN operation = 'erase' THEN
        CASE WHEN json_type(details, '$.scope') = 'text'
                AND json_extract(details, '$.scope') IN ('project', 'global')
            THEN json_object('scope', json_extract(details, '$.scope'))
            ELSE json_object() END
    WHEN operation = 'compress_commit' THEN
        CASE WHEN json_type(details, '$.summaries') = 'array'
            THEN json_object('summary_count', json_array_length(details, '$.summaries'))
            WHEN json_type(details, '$.summary_count') = 'integer'
                    AND json_extract(details, '$.summary_count') >= 0
                THEN json_object(
                    'summary_count', json_extract(details, '$.summary_count')
                )
            ELSE json_object() END
    ELSE json_object()
END;
