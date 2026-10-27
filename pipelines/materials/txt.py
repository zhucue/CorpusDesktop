"""Strict bounded UTF-8 TXT import with lossless canonical coordinates."""
import codecs
import hashlib
import re
import time
from pathlib import Path
from uuid import UUID

from pipelines.query.source_recipe import encoded

ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT_BYTES = 100_000_000
MAX_SEGMENT_CODEPOINTS = 100_000
RECIPE = {"id": "utf8-txt/v1", "encoding": "strict UTF-8", "normalization": "none",
          "bom": "remove one initial UTF-8 BOM; affine original codepoint/byte prefix mapping",
          "newlines": "preserve CRLF, CR and LF verbatim", "whitespace": "preserve all; attach to neighbouring content",
          "segments": "newline or terminal punctuation; closing quotes; English abbreviations/initials protected",
          "abbreviations": ["Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "e.g.", "i.e."],
          "max_input_bytes": MAX_INPUT_BYTES, "max_segment_codepoints": MAX_SEGMENT_CODEPOINTS}
RECIPE_ID = RECIPE['id']
RECIPE_SHA256 = hashlib.sha256(encoded(RECIPE)).hexdigest()
BOUNDARY = re.compile(r'[。！？][”’\"\'）)\]]*\s*|[.!?][”’\"\'）)\]]*(?=\s|$)\s*|\r\n\s*|[\r\n]\s*')
ABBREVIATION = re.compile(r'(?:\b(?:Mr|Mrs|Ms|Dr|Prof)|\be\.g|\bi\.e|\b[A-Za-z])\.$', re.IGNORECASE)


class MaterialError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _segments(buffer, final=False):
    """Yield complete prefixes; leave the final potentially incomplete sentence."""
    start = 0
    for match in BOUNDARY.finditer(buffer):
        if match.end() == len(buffer) and not final:
            break
        if buffer[match.start()] == '.' and ABBREVIATION.search(buffer[:match.start()+1]):
            continue
        if not buffer[start:match.end()].strip():
            continue
        yield start, match.end()
        start = match.end()
    if final and start < len(buffer):
        yield start, len(buffer)


def parse_txt(raw_path, output_dir, *, document_id, revision_id, language,
              expected_sha256, expected_bytes, progress_callback, max_temporary_bytes=512*1024**2):
    """Write complete immutable derived artifacts; caller owns storage and authorization."""
    raw, output = Path(raw_path).resolve(), Path(output_dir).resolve()
    if language not in ('cmn', 'eng'):
        raise MaterialError('MATERIAL_LANGUAGE_UNSUPPORTED')
    try:
        UUID(str(document_id)); UUID(str(revision_id))
    except (ValueError, TypeError, AttributeError):
        raise MaterialError('MATERIAL_ID_INVALID') from None
    if (not re.fullmatch('[0-9a-f]{64}', expected_sha256) or type(expected_bytes) is not int
            or not 0 < expected_bytes <= MAX_INPUT_BYTES):
        raise MaterialError('MATERIAL_INPUT_LIMIT')
    if raw.is_symlink() or not raw.is_file() or raw.stat().st_size != expected_bytes:
        raise MaterialError('MATERIAL_INPUT_MISMATCH')
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise MaterialError('MATERIAL_OUTPUT_INVALID')
    output.mkdir(parents=True)
    started, last = time.monotonic(), 0
    read_bytes = cp = byte = ordinal = 0
    raw_hash, text_hash = hashlib.sha256(), hashlib.sha256()
    prefix, buffer = 0, ''
    decoder = codecs.getincrementaldecoder('utf-8')('strict')

    def tick(force=False):
        nonlocal last
        now = time.monotonic()
        if now-started > 300:
            raise MaterialError('MATERIAL_TIMEOUT')
        if force or now-last >= 1:
            size = expected_bytes+sum(p.stat().st_size for p in output.iterdir() if p.is_file())
            if size > max_temporary_bytes:
                raise MaterialError('MATERIAL_QUOTA_EXCEEDED')
            progress_callback({'stage':'PARSING','processed_bytes':read_bytes,'total_bytes':expected_bytes,
                               'processed_records':ordinal,'total_records':None,'workspace_bytes':size,
                               'workspace_limit_bytes':max_temporary_bytes})
            last = now

    try:
        tick(True)
        with raw.open('rb') as source, (output/'canonical.utf8').open('xb') as canonical, (output/'segments.jsonl').open('xb') as rows:
            first = True
            while True:
                chunk = source.read(65536)
                raw_hash.update(chunk)
                read_bytes += len(chunk)
                if read_bytes > expected_bytes:
                    raise MaterialError('MATERIAL_INPUT_MISMATCH')
                text = decoder.decode(chunk, final=not chunk)
                if first:
                    prefix = int(text.startswith('\ufeff'))
                    text = text[prefix:]
                    first = False
                if '\x00' in text:
                    raise MaterialError('MATERIAL_NUL_REJECTED')
                data = text.encode('utf-8')
                canonical.write(data); text_hash.update(data)
                buffer += text
                consumed = 0
                for left, right in _segments(buffer, final=not chunk):
                    segment = buffer[left:right]
                    if not segment.strip():
                        raise MaterialError('MATERIAL_EMPTY')
                    if len(segment) > MAX_SEGMENT_CODEPOINTS:
                        raise MaterialError('MATERIAL_SEGMENT_TOO_LARGE')
                    size = len(segment.encode('utf-8'))
                    rows.write(encoded({'ordinal':ordinal,'segment_id':f'{revision_id}:s:{ordinal}',
                                        'start_cp':cp,'end_cp':cp+len(segment),'byte_start':byte,'byte_end':byte+size})+b'\n')
                    cp += len(segment); byte += size; ordinal += 1; consumed = right
                buffer = buffer[consumed:]
                if len(buffer) > MAX_SEGMENT_CODEPOINTS:
                    raise MaterialError('MATERIAL_SEGMENT_TOO_LARGE')
                tick()
                if not chunk:
                    break
        if read_bytes != expected_bytes or raw_hash.hexdigest() != expected_sha256:
            raise MaterialError('MATERIAL_INPUT_MISMATCH')
        if not ordinal:
            raise MaterialError('MATERIAL_EMPTY')
        files = []
        for p in (output/'canonical.utf8',output/'segments.jsonl'):
            with p.open('rb') as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            files.append({'name':p.name,'bytes':p.stat().st_size,'sha256':sha})
        counts = {'documents':1,'segments':ordinal,'characters':cp,'input_bytes':read_bytes,'canonical_bytes':byte}
        manifest = {'format':'private-txt/v1','recipe':RECIPE,'recipe_id':RECIPE_ID,'recipe_sha256':RECIPE_SHA256,
                    'document_id':str(document_id),'revision_id':str(revision_id),'language':language,
                    'input':{'bytes':read_bytes,'sha256':expected_sha256},'counts':counts,'files':files,
                    'source_mapping':{'kind':'identity_codepoints_after_prefix','source_codepoint_prefix':prefix,'source_byte_prefix':prefix*3},
                    'quality':{'complete_text_preserved':True,'rejected_segments':0,'segmentation':'deterministic_rules_not_linguistic_gold'}}
        tick(True)
        manifest_path = output/'manifest.json'
        manifest_path.write_bytes(encoded(manifest))
        try:
            tick(True)
        except BaseException:
            manifest_path.unlink(missing_ok=True)
            raise
        artifacts=[]
        for p in (output/'canonical.utf8',output/'segments.jsonl',manifest_path):
            with p.open('rb') as stream:
                sha=hashlib.file_digest(stream,'sha256').hexdigest()
            artifacts.append({'name':p.name,'path':p,'bytes':p.stat().st_size,'sha256':sha})
        return {'manifest':manifest,'manifest_path':manifest_path,'counts':counts,'artifacts':artifacts}
    except UnicodeDecodeError:
        raise MaterialError('MATERIAL_ENCODING_INVALID') from None
