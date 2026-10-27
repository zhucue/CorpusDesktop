"""Stream fixed rows to exact JSON or a documented CSV research package."""
import csv
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path
from uuid import uuid4

RECIPE_ID = 'research-export/v1'
RECIPE_SHA256 = hashlib.sha256(b'research-export/v1:json-exact:csv-text-prefix-v1:zip-stored:ordered-full-results:row-number-per-run').hexdigest()
MAX_BYTES = 512 * 1024**2
MAX_ROW_BYTES = 2 * 1024**2
MAX_METHOD_BYTES = 1024**2
QUERY_FIELDS = (
    'record_type', 'row_number', 'hit_ref', 'query_run_id', 'result_set_id', 'snapshot_id',
    'document_id', 'revision_id', 'segment_id', 'origin_kind', 'material_id',
    'source_id', 'source_sentence_id', 'source_url', 'language', 'owner', 'license',
    'start_cp', 'end_cp', 'context_start_cp', 'token_start', 'token_end',
    'global_token_start', 'global_token_end', 'left', 'match', 'right', 'provenance',
)
NOTE_FIELDS = ('record_type', 'note_id', 'revision', 'title', 'body', 'status',
               'evidence_refs', 'query_run_ids', 'authorization_evidence_ids',
               'authorization_query_run_ids')
CSV_ENCODING = {
    'recipe': 'text-prefix/v1', 'charset': 'UTF-8', 'bom': False,
    'record_separator': 'CRLF', 'quoting': 'all fields; embedded quotes doubled',
    'text': 'Every nonempty string has exactly one leading ASCII apostrophe added; remove exactly one to recover it.',
    'numbers': 'JSON numeric fields remain numeric decimal cells.',
    'null_and_empty': 'Both use an empty cell; use JSON to distinguish null from empty string.',
    'nested_values': 'Objects and arrays use compact JSON encoded as a prefixed text cell.',
    'scope': 'Initial text-oriented import only; not a guarantee across spreadsheet programs or save/reopen cycles.',
    'references': ['https://www.rfc-editor.org/rfc/rfc4180.html',
                   'https://community.owasp.org/attacks/CSV_Injection'],
}


class ExportError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':'), sort_keys=True).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ExportError('EXPORT_INVALID_INPUT') from exc


class Guard:
    def __init__(self, callback, expected_rows, timeout):
        self.callback, self.total = callback, expected_rows
        self.deadline, self.last = time.monotonic() + timeout, 0
        self.rows, self.bytes = 0, 0

    def tick(self, *, force=False, stage='RENDERING'):
        now = time.monotonic()
        if now > self.deadline:
            raise ExportError('EXPORT_TIMEOUT')
        if force or now - self.last >= 1:
            self.callback({'stage': stage, 'processed_records': self.rows,
                           'total_records': self.total, 'processed_bytes': self.bytes,
                           'total_bytes': None})
            self.last = now


class _BoundedFile:
    """ZipFile may seek back to headers: budget the high-water file length."""
    def __init__(self, stream, limit, guard):
        self.stream, self.limit, self.guard = stream, limit, guard
        self.peak = 0

    def write(self, data):
        self.guard.tick()
        size = max(self.peak, self.stream.tell() + len(data))
        if size > self.limit:
            raise ExportError('EXPORT_TOO_LARGE')
        result = self.stream.write(data)
        self.peak = size
        self.guard.bytes = size
        return result

    def tell(self):
        return self.stream.tell()

    def seek(self, *args):
        return self.stream.seek(*args)

    def flush(self):
        return self.stream.flush()


def _csv_value(value):
    if value is None or value == '':
        return ''
    if type(value) in (int, float):
        return value
    if not isinstance(value, str):
        value = _json(value).decode('utf-8')
    return "'" + value


def _csv_row(values):
    text = io.StringIO(newline='')
    csv.writer(text, quoting=csv.QUOTE_ALL, lineterminator='\r\n').writerow(values)
    return text.getvalue().encode('utf-8')


def _rows(rows, fields, kind, expected, guard, query_counts):
    run_index, local_row = 0, 0
    for ordinal, row in enumerate(rows, 1):
        guard.tick()
        if ordinal > expected:
            raise ExportError('EXPORT_COUNT_MISMATCH')
        if not isinstance(row, dict) or set(row) != set(fields):
            raise ExportError('EXPORT_INVALID_INPUT')
        if kind == 'query':
            run = row['query_run_id']
            while run_index < len(query_counts) and local_row == query_counts[run_index][2]:
                run_index += 1
                local_row = 0
            if (run_index == len(query_counts) or run != query_counts[run_index][0]
                    or row['result_set_id'] != query_counts[run_index][1]):
                raise ExportError('EXPORT_COUNT_MISMATCH')
            local_row += 1
            if (row['record_type'] != 'query_hit' or type(row['row_number']) is not int
                    or row['row_number'] != local_row
                    or row['hit_ref'] != {'result_set_id': row['result_set_id'], 'ordinal': local_row-1}):
                raise ExportError('EXPORT_INVALID_INPUT')
        elif row['record_type'] != 'note_revision' or row['status'] not in ('draft', 'accepted'):
            raise ExportError('EXPORT_INVALID_INPUT')
        encoded = _json(row)
        if len(encoded) > MAX_ROW_BYTES:
            raise ExportError('EXPORT_TOO_LARGE')
        yield row, encoded
        guard.rows = ordinal
    if guard.rows != expected:
        raise ExportError('EXPORT_COUNT_MISMATCH')


def render_export(output_dir, *, format, kind, methods, rows, expected_rows,
                  progress_callback, max_bytes=MAX_BYTES,
                  max_temporary_bytes=MAX_BYTES, timeout=600):
    """Return one immutable candidate artifact; caller authorizes and publishes.

    The trusted caller supplies rows(checkpoint), an ordered iterator factory, and fixed
    method metadata. No queries, network access or authorization occur here.
    Failure removes only this invocation's partial file; existing files stay.
    """
    if (format not in ('json', 'csv') or kind not in ('query', 'notes')
            or type(expected_rows) is not int or expected_rows < 0
            or not isinstance(methods, dict) or not callable(rows) or not 0 < max_bytes <= MAX_BYTES
            or not 0 < max_temporary_bytes <= MAX_BYTES or not 0 < timeout <= 600):
        raise ExportError('EXPORT_INVALID_INPUT')
    fields = QUERY_FIELDS if kind == 'query' else NOTE_FIELDS
    query_counts = []
    if kind == 'query':
        try:
            query_counts = [(q['query_run_id'], q['result_set_id'], q['counts']['total_hits'])
                            for q in methods['queries']]
            if (not 1 <= len(query_counts) <= 16
                    or len({q[0] for q in query_counts}) != len(query_counts)
                    or any(not isinstance(q[0], str) or not q[0] or not isinstance(q[1], str)
                           or not q[1] or type(q[2]) is not int or q[2] < 0 for q in query_counts)
                    or sum(q[2] for q in query_counts) != expected_rows):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ExportError('EXPORT_INVALID_INPUT') from exc
    elif expected_rows != 1:
        raise ExportError('EXPORT_INVALID_INPUT')
    method_bytes = _json({'recipe_id': RECIPE_ID, 'recipe_sha256': RECIPE_SHA256,
                          'kind': kind, 'row_count': expected_rows,
                          'row_unit': 'exported rows; no cross-query deduplication',
                          'row_numbering': 'row_number is 1-based within each query run; hit_ref.ordinal remains 0-based',
                          'methods': methods, 'csv_encoding': CSV_ENCODING if format == 'csv' else None})
    if len(method_bytes) > MAX_METHOD_BYTES:
        raise ExportError('EXPORT_TOO_LARGE')
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ExportError('EXPORT_INVALID_PATH')
    # Caller supplies a task-private workspace. Existing occupancy consumes budget.
    occupied = sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
    limit = min(max_bytes, max_temporary_bytes - occupied)
    if limit <= 0:
        raise ExportError('EXPORT_TOO_LARGE')
    name = 'results.json' if format == 'json' else 'results.zip'
    target, partial = directory/name, directory/(name+'.partial-'+uuid4().hex)
    if target.exists():
        raise ExportError('EXPORT_ALREADY_EXISTS')
    guard = Guard(progress_callback, expected_rows, timeout)
    guard.tick(force=True)
    try:
        with partial.open('xb') as raw:
            out = _BoundedFile(raw, limit, guard)
            if format == 'json':
                out.write(method_bytes[:-1] + b',"rows":[')
                for row, encoded in _rows(rows(guard.tick), fields, kind, expected_rows, guard, query_counts):
                    if guard.rows:
                        out.write(b',')
                    out.write(encoded)
                out.write(b']}\n')
            else:
                with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as package:
                    package.writestr(zipfile.ZipInfo('methods.json', (1980, 1, 1, 0, 0, 0)), method_bytes+b'\n')
                    with package.open(zipfile.ZipInfo('results.csv', (1980, 1, 1, 0, 0, 0)), 'w') as table:
                        table.write(_csv_row(fields))
                        for row, _ in _rows(rows(guard.tick), fields, kind, expected_rows, guard, query_counts):
                            table.write(_csv_row([_csv_value(row[key]) for key in fields]))
            raw.flush()
            os.fsync(raw.fileno())
        digest = hashlib.sha256()
        with partial.open('rb') as stream:
            while chunk := stream.read(1024**2):
                digest.update(chunk)
                guard.tick(stage='VERIFYING')
        guard.tick(force=True, stage='VERIFYING')
        # No second archive copy: same-directory rename preserves byte budget.
        if target.exists():
            raise ExportError('EXPORT_ALREADY_EXISTS')
        partial.rename(target)
        return {'path': target, 'name': name,
                'media_type': 'application/json' if format == 'json' else 'application/zip',
                'bytes': target.stat().st_size, 'sha256': digest.hexdigest(),
                'row_count': expected_rows, 'format': format, 'recipe_id': RECIPE_ID,
                'recipe_sha256': RECIPE_SHA256,
                'sampled_workspace_bytes': occupied + out.peak}
    finally:
        partial.unlink(missing_ok=True)
