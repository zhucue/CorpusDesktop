"""Read full persisted query spans without matching again or loading the corpus."""
import hashlib
import json
from pathlib import Path

from pipelines.exports.render import ExportError, Guard
from pipelines.query.source_results import ABSENT, MAX_SPAN_BYTES, SPAN


def attribution_for_ordinals(reader, ordinals, *, single_source_id=None, checkpoint=lambda: None):
    """At most 100 note references, one monotone legacy member scan per index."""
    requested = sorted(set(ordinals))
    if (len(requested) > 100 or any(type(i) is not int or not 0 <= i < reader.count for i in requested)
            or (not reader.is_project and not single_source_id)):
        raise ExportError('EXPORT_INVALID_INPUT')
    found = {}
    if reader.is_project:
        for ordinal in requested:
            checkpoint()
            found[ordinal] = reader.metadata(ordinal)
    elif requested:
        at = 0
        with (reader.directory/'members.jsonl').open('r', encoding='utf-8') as stream:
            for ordinal, line in enumerate(stream):
                checkpoint()
                if ordinal != requested[at]:
                    continue
                meta = json.loads(line)
                if (meta['ordinal'] != ordinal or meta['id'] != reader.record(ordinal)[0]
                        or meta['revision_id'] != reader.metadata(ordinal)['revision_id']):
                    raise ExportError('EXPORT_SOURCE_METADATA_INVALID')
                found[ordinal] = {**meta, 'origin_kind':'source', 'source_id':single_source_id}
                at += 1
                if at == len(requested):
                    break
        if len(found) != len(requested):
            raise ExportError('EXPORT_SOURCE_METADATA_INVALID')
    result = {}
    for ordinal, meta in found.items():
        private = meta['origin_kind'] == 'private'
        result[ordinal] = {
            'origin_kind': meta['origin_kind'],
            'source_id': None if private else meta.get('source_id'),
            'owner': None if private else meta.get('owner'),
            'license': None if private else meta.get('license'),
            'source_url': None if private else meta.get('source_url'),
            'language': meta.get('language'),
            'provenance': {key: meta.get(key) for key in ('added', 'modified',
                'source_line', 'record_sha256', 'canonical_sha256', 'text_sha256', 'source_mapping')},
        }
    return result


def iter_query_rows(reader, span_path, *, expected_sha256, expected_records,
                    result_set_id, query_run_id, snapshot_id, single_source_id=None,
                    context_codepoints=40, progress_callback=lambda _: None, checkpoint=lambda: None):
    """Ordered complete result, with actual upstream attribution from index bytes.

    Caller pins/authorizes index and result versions. This iterator verifies the
    complete span digest before yielding; no CQP process or query AST is used.
    Legacy source member metadata is scanned once, monotonically by ordinal.
    """
    if (type(expected_records) is not int or expected_records < 0
            or expected_records * SPAN.size > MAX_SPAN_BYTES
            or (not reader.is_project and not single_source_id)):
        raise ExportError('EXPORT_INVALID_INPUT')
    guard = Guard(progress_callback, expected_records, 600)
    def tick(stage='RENDERING'):
        checkpoint()  # One renderer deadline across every input run, including hash scans.
        guard.tick(stage=stage)
    path = Path(span_path)
    if path.is_symlink() or path.stat().st_size != expected_records * SPAN.size:
        raise ExportError('EXPORT_RESULT_MISMATCH')
    # Keep the same open inode for verification and use, including empty results.
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        while chunk := stream.read(1024**2):
            digest.update(chunk)
            tick('VERIFYING')
        if digest.hexdigest() != expected_sha256:
            raise ExportError('EXPORT_RESULT_MISMATCH')
        stream.seek(0)
        source_rows = None
        try:
            if not reader.is_project:
                source_rows = (reader.directory/'members.jsonl').open('r', encoding='utf-8')
            source_ordinal, source_meta, previous = -1, None, None
            for result_ordinal in range(expected_records):
                tick()
                raw = stream.read(SPAN.size)
                if len(raw) != SPAN.size:
                    raise ExportError('EXPORT_RESULT_MISMATCH')
                span = SPAN.unpack(raw)
                sentence, left, right, first, last = span
                if previous is not None and span <= previous:
                    raise ExportError('EXPORT_RESULT_MISMATCH')
                if (first == ABSENT) != (last == ABSENT):
                    raise ExportError('EXPORT_RESULT_MISMATCH')
                hit = reader.span_hit(sentence, left, right,
                                      None if first == ABSENT else first,
                                      None if last == ABSENT else last,
                                      context_codepoints=context_codepoints)
                meta = reader.metadata(sentence)
                if source_rows is not None:
                    while source_ordinal < sentence:
                        line = source_rows.readline(2 * 1024**2 + 1)
                        if not line or len(line) > 2 * 1024**2:
                            raise ExportError('EXPORT_SOURCE_METADATA_INVALID')
                        source_meta = json.loads(line)
                        source_ordinal += 1
                        if source_meta['ordinal'] != source_ordinal:
                            raise ExportError('EXPORT_SOURCE_METADATA_INVALID')
                        tick()
                    if (source_meta['id'] != reader.record(sentence)[0]
                            or source_meta['revision_id'] != meta['revision_id']):
                        raise ExportError('EXPORT_SOURCE_METADATA_INVALID')
                    meta = {**meta, **source_meta, 'source_id': single_source_id}
                private = meta['origin_kind'] == 'private'
                yield {
                    'record_type': 'query_hit', 'row_number': result_ordinal+1,
                    'hit_ref': {'result_set_id': result_set_id, 'ordinal': result_ordinal},
                    'query_run_id': query_run_id, 'result_set_id': result_set_id,
                    'snapshot_id': snapshot_id, 'document_id': hit['document_id'],
                    'revision_id': hit['revision_id'], 'segment_id': hit['segment_id'],
                    'origin_kind': meta['origin_kind'],
                    'material_id': hit['material_id'], 'source_id': None if private else meta.get('source_id'),
                    'source_sentence_id': None if private else str(meta['source_sentence_id']),
                    'source_url': None if private else meta.get('source_url'),
                    'language': meta.get('language'), 'owner': None if private else meta.get('owner'),
                    'license': None if private else meta.get('license'),
                    **{key: hit[key] for key in ('start_cp', 'end_cp', 'context_start_cp',
                       'token_start', 'token_end', 'global_token_start', 'global_token_end',
                       'left', 'match', 'right')},
                    'provenance': {key: meta.get(key) for key in ('added', 'modified',
                        'source_line', 'record_sha256', 'canonical_sha256', 'text_sha256', 'source_mapping')},
                }
                previous = span
                guard.rows = result_ordinal+1
            if stream.read(1):
                raise ExportError('EXPORT_RESULT_MISMATCH')
            guard.tick(force=True)
            checkpoint()
        finally:
            if source_rows is not None:
                source_rows.close()
