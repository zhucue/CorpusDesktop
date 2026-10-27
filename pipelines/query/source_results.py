"""Bounded exact query artifacts. No database, credentials or authorization here."""
import hashlib
import json
import os
import re
import struct
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

from contracts.semantics import validate_query_semantics
from pipelines.query.cwb import _union_commands
from pipelines.query.engine import QueryError
from pipelines.query.source_index import TOKEN, digest
from pipelines.query.source_reader import storage_query
from pipelines.query.source_recipe import encoded

SPAN = struct.Struct('<QIIQQ')
ABSENT = 2**64 - 1
MAX_SPAN_BYTES = 512 * 1024**2
MAX_CQP_BYTES = 1024**3
FORMAT = 'source-query-spans/u64-u32-u32-u64-u64-v1'


def validate_query(query):
    """Cheap supported-subset check, safe to run in the API without CWB."""
    schema_path = Path(__file__).resolve().parents[2] / 'contracts/schemas/corpus-query.schema.json'
    try:
        if len(encoded(query)) > 65536:
            raise ValueError('large AST')
        Draft202012Validator(json.loads(schema_path.read_text('utf-8'))).validate(query)
        validate_query_semantics(query)
        if query['within'] != 'sentence' or query.get('condition') or query.get('filters'):
            raise ValueError('unsupported scope')
        if query['unit'] == 'token':
            _union_commands(storage_query(query), 'SOURCE', frozenset({'form'}))
    except (ValueError, ValidationError, KeyError, TypeError, UnicodeError) as exc:
        raise QueryError('QUERY_UNSUPPORTED') from exc


class _Guard:
    def __init__(self, callback, timeout):
        self.callback, self.deadline = callback, time.monotonic() + timeout
        self.last, self.records = 0, 0
        self.stage = 'MATCHING'

    def tick(self, *, force=False):
        now = time.monotonic()
        if now > self.deadline:
            raise QueryError('QUERY_TIMEOUT')
        if force or now - self.last >= 1:
            self.callback({'stage': self.stage, 'processed_records': self.records,
                           'total_records': None, 'processed_bytes': None, 'total_bytes': None})
            self.last = now


def _token_spans(reader, query, guard, *, limit=None, max_dump_bytes=MAX_CQP_BYTES):
    if reader.runtime is None:
        raise QueryError('QUERY_ENGINE_REQUIRED')
    command = _union_commands(storage_query(query), 'SOURCE', frozenset({'form'}))
    command += 'dump M' + (f' 0 {limit-1}' if limit is not None else '') + ';\nexit;\n'
    prefix = reader.runtime / ('query-' + uuid4().hex)
    output, errors, input_path = [prefix.with_suffix(s) for s in ('.stdout', '.stderr', '.stdin')]
    input_path.write_text(command, encoding='utf-8')
    try:
        with input_path.open('rb') as stdin, output.open('xb') as stdout, errors.open('xb') as stderr:
            process = subprocess.Popen([str(reader.executable), '-c', '-r', str(reader.registry)],
                                       stdin=stdin, stdout=stdout, stderr=stderr)
            try:
                while process.poll() is None:
                    guard.tick()
                    if output.stat().st_size > max_dump_bytes or errors.stat().st_size > 1024**2:
                        raise QueryError('QUERY_RESULT_TOO_LARGE')
                    time.sleep(.2)
                guard.tick(force=True)
                if output.stat().st_size > max_dump_bytes or errors.stat().st_size > 1024**2:
                    raise QueryError('QUERY_RESULT_TOO_LARGE')
                if process.returncode:
                    raise QueryError('QUERY_ENGINE_FAILED')
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
        if re.search(r'\b(error|undefined)\b', errors.read_text('utf-8'), re.IGNORECASE):
            raise QueryError('QUERY_ENGINE_FAILED')
        previous, count = None, 0
        with output.open(encoding='utf-8') as stream:
            for line in stream:
                guard.tick()
                if not line.strip() or line.startswith('CQP version '):
                    continue
                fields = line.rstrip('\n').split('\t')
                if len(fields) != 4 or not all(re.fullmatch(r'-?\d+', f) for f in fields):
                    raise QueryError('QUERY_ENGINE_OUTPUT_INVALID')
                start, end = int(fields[0]), int(fields[1]) + 1
                if not 0 <= start < end <= reader.manifest['counts']['tokens'] or (previous is not None and (start, end) <= previous):
                    raise QueryError('QUERY_ENGINE_OUTPUT_INVALID')
                ordinal, left, _ = TOKEN.unpack_from(reader.maps['tokens.map'], start * TOKEN.size)
                last, _, right = TOKEN.unpack_from(reader.maps['tokens.map'], (end-1) * TOKEN.size)
                if ordinal != last:
                    raise QueryError('QUERY_CROSS_SENTENCE_HIT')
                count += 1
                if limit is not None and count > limit:
                    raise QueryError('QUERY_ENGINE_OUTPUT_INVALID')
                previous = start, end
                yield ordinal, left, right, start, end
    finally:
        for path in (output, errors, input_path):
            path.unlink(missing_ok=True)


def _spans(reader, query, guard, *, limit=None):
    validate_query(query)
    if query['unit'] == 'character':
        for count, (ordinal, left, right) in enumerate(reader._character_matches(query, guard.tick), 1):
            yield ordinal, left, right, ABSENT, ABSENT
            if limit is not None and count >= limit:
                break
    else:
        yield from _token_spans(reader, query, guard, limit=limit)


def _hit(reader, span, ordinal, context_codepoints):
    sentence, left, right, token_start, token_end = span
    if (token_start == ABSENT) != (token_end == ABSENT):
        raise QueryError('RESULT_SPAN_INVALID')
    return {**reader.span_hit(sentence, left, right,
                             None if token_start == ABSENT else token_start,
                             None if token_end == ABSENT else token_end,
                             context_codepoints=context_codepoints), 'result_ordinal': ordinal}


def first_page(reader, query, *, context_codepoints=40, limit=50, progress_callback=lambda _: None, timeout=120):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('INVALID_PAGE')
    guard = _Guard(progress_callback, timeout)
    guard.tick(force=True)
    spans = list(_spans(reader, query, guard, limit=limit+1))
    guard.tick(force=True)
    return {'hits': [_hit(reader, span, i, context_codepoints) for i, span in enumerate(spans[:limit])],
            'has_more': len(spans) > limit}


def _marker(path):
    return path.with_name(path.name + '.ready.json')


def _publish(path, partial, metadata):
    if path.exists() or _marker(path).exists():
        raise QueryError('RESULT_ALREADY_EXISTS')
    os.replace(partial, path)
    temporary = _marker(path).with_suffix('.tmp-' + uuid4().hex)
    temporary.write_bytes(encoded(metadata))
    os.replace(temporary, _marker(path))


def write_spans(reader, query, output_path, progress_callback, *, max_bytes=MAX_SPAN_BYTES, timeout=120):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.partial-' + uuid4().hex)
    guard = _Guard(progress_callback, timeout)
    digest_value = hashlib.sha256()
    records, sentences, previous, previous_sentence = 0, 0, None, None
    documents = source_documents = private_documents = 0
    previous_document = None
    try:
        with partial.open('xb') as stream:
            for span in _spans(reader, query, guard):
                if previous is not None and span <= previous:
                    raise QueryError('RESULT_SPANS_NOT_SORTED_UNIQUE')
                if (records+1) * SPAN.size > min(max_bytes, MAX_SPAN_BYTES):
                    raise QueryError('QUERY_RESULT_TOO_LARGE')
                data = SPAN.pack(*span)
                stream.write(data)
                digest_value.update(data)
                records += 1
                if span[0] != previous_sentence:
                    sentences += 1
                    document = reader.document_ordinal(span[0])
                    if document != previous_document:
                        documents += 1
                        private = reader.is_project and reader.metadata(span[0])['origin_kind'] == 'private'
                        private_documents += private
                        source_documents += not private
                    previous_document = document
                previous, previous_sentence = span, span[0]
                guard.records = records
                guard.tick()
            stream.flush()
            os.fsync(stream.fileno())
        metadata = {'format': FORMAT, 'bytes': records*SPAN.size, 'sha256': digest_value.hexdigest(),
                    'record_count': records, 'index_identity_sha256': reader.manifest['identity_sha256'],
                    'query_sha256': hashlib.sha256(encoded(query)).hexdigest()}
        guard.tick(force=True)
        _publish(path, partial, metadata)
        counts = {'total_hits':records,'matched_segments':sentences,'matched_documents':documents,
                  'document_count_unit':'document' if reader.is_project else 'imported_sentence_record'}
        if reader.is_project:
            counts.update(matched_source_documents=source_documents,matched_private_documents=private_documents)
        return {**metadata, 'path':path, 'counts':counts}
    finally:
        partial.unlink(missing_ok=True)


def install_result(stream, expected_bytes, expected_sha256, target_path, callback, *, max_bytes=MAX_SPAN_BYTES):
    from pipelines.query.source_cache import _lock
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    guard = _Guard(callback, 1800)
    with _lock(path.parent, guard.tick):
        if path.is_symlink() or _marker(path).is_symlink():
            raise QueryError('RESULT_CACHE_INVALID')
        if path.exists() or _marker(path).exists():
            try:
                marker = json.loads(_marker(path).read_text('utf-8'))
                valid = (marker['format'] == FORMAT and marker['bytes'] == expected_bytes
                         and marker['sha256'] == expected_sha256
                         and marker['record_count'] == expected_bytes//SPAN.size
                         and path.stat().st_size == expected_bytes)
            except (ValueError, KeyError, TypeError, OSError):
                valid = False
            if valid and digest(path, guard.tick) == expected_sha256:
                return {**marker, 'path': path}
            path.unlink(missing_ok=True)
            _marker(path).unlink(missing_ok=True)
        return _install_result(stream, expected_bytes, expected_sha256, path, callback, max_bytes=max_bytes)


def _install_result(stream, expected_bytes, expected_sha256, target_path, callback, *, max_bytes):
    """Restore exact immutable result bytes; caller pins version and authorizes."""
    if expected_bytes < 0 or expected_bytes % SPAN.size or expected_bytes > min(max_bytes, MAX_SPAN_BYTES):
        raise QueryError('QUERY_RESULT_TOO_LARGE')
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.partial-' + uuid4().hex)
    guard = _Guard(callback, 1800)
    try:
        total, h = 0, hashlib.sha256()
        with partial.open('xb') as out:
            while chunk := stream.read(1024**2):
                total += len(chunk)
                if total > expected_bytes:
                    raise QueryError('RESULT_HASH_MISMATCH')
                out.write(chunk)
                h.update(chunk)
                guard.tick()
            out.flush()
            os.fsync(out.fileno())
        if total != expected_bytes or h.hexdigest() != expected_sha256:
            raise QueryError('RESULT_HASH_MISMATCH')
        metadata = {'format': FORMAT, 'bytes': total, 'sha256': expected_sha256, 'record_count': total//SPAN.size}
        guard.tick(force=True)
        _publish(path, partial, metadata)
        return {**metadata, 'path': path}
    finally:
        partial.unlink(missing_ok=True)


def read_page(reader, span_path, offset=0, *, limit=50, context_codepoints=40, expected_sha256, expected_records):
    """Only positional reads from the worker-verified, API-readonly volume."""
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('INVALID_PAGE')
    path = Path(span_path)
    try:
        metadata = json.loads(_marker(path).read_text('utf-8'))
        if path.is_symlink() or metadata['format'] != FORMAT or metadata['sha256'] != expected_sha256 or metadata['record_count'] != expected_records or metadata['bytes'] != expected_records*SPAN.size or path.stat().st_size != metadata['bytes']:
            raise QueryError('RESULT_CACHE_INVALID')
        if metadata.get('index_identity_sha256', reader.manifest['identity_sha256']) != reader.manifest['identity_sha256']:
            raise QueryError('RESULT_CACHE_INVALID')
        hits = []
        with path.open('rb') as stream:
            stream.seek(offset*SPAN.size)
            for i in range(offset, min(offset+limit, expected_records)):
                data = stream.read(SPAN.size)
                if len(data) != SPAN.size:
                    raise QueryError('RESULT_CACHE_INVALID')
                hits.append(_hit(reader, SPAN.unpack(data), i, context_codepoints))
        return {'hits': hits, 'has_more': offset+len(hits) < expected_records}
    except FileNotFoundError as exc:
        raise QueryError('CACHE_NOT_READY') from exc
    except (ValueError, KeyError, TypeError, OSError, struct.error) as exc:
        raise QueryError('RESULT_CACHE_INVALID') from exc


def verify_result(path, expected_sha256):
    """Explicit worker verification, never an implicit per-page full-file read."""
    if digest(Path(path)) != expected_sha256:
        raise QueryError('RESULT_HASH_MISMATCH')
