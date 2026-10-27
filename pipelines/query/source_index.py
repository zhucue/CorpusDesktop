"""Bounded immutable full-source index builder; no publication or authorization."""
import hashlib
import mmap
import re
import sqlite3
import struct
import subprocess
import tarfile
import time
from collections import Counter
from pathlib import Path

from pipelines.query.source_recipe import (
    RECIPE,
    RECIPE_ID,
    RECIPE_SHA256,
    SurfaceTokenizer,
    encoded,
    storage_key,
)

ROOT = Path(__file__).resolve().parents[2]
TOKEN = struct.Struct("<III")
RECORD = struct.Struct("<QQQQQQ")  # source id, text byte start/length, global cp start/length, token start
U64 = struct.Struct("<Q")
MAX_TEMPORARY_BYTES = 8 * 1024**3
MAX_ARTIFACT_BYTES = 4 * 1024**3
LIMITS = {"sentences": 3_000_000, "characters": 250_000_000, "tokens": 250_000_000,
          "sentence_characters": 100_000, "stage_seconds": 1800, "total_seconds": 7200}


class _ProgressReader:
    def __init__(self, stream, guard):
        self.stream, self.guard = stream, guard

    def read(self, size):
        self.guard.tick()
        return self.stream.read(size)


class IndexBuildError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def digest(path, tick=None):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
            if tick:
                tick()
    return h.hexdigest()


class Guard:
    def __init__(self, output, input_bytes, callback, maximum):
        self.output, self.input_bytes, self.callback, self.maximum = output, input_bytes, callback, maximum
        self.started = self.stage_started = time.monotonic()
        self.last = 0
        self.stage = "VALIDATING"
        self.records = 0
        self.total = None
        self.peak = input_bytes

    def tick(self, *, stage=None, records=None, total=None, force=False):
        now = time.monotonic()
        if stage and stage != self.stage:
            self.stage, self.stage_started = stage, now
            force = True
        if records is not None:
            self.records = records
        if total is not None:
            self.total = total
        if now - self.started > LIMITS["total_seconds"] or now - self.stage_started > LIMITS["stage_seconds"]:
            raise IndexBuildError("INDEX_BUILD_TIMEOUT")
        if force or now - self.last >= 1:
            size = self.input_bytes
            for path in self.output.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except FileNotFoundError:
                    pass  # CWB may remove an intermediate between directory scan and stat.
            self.peak = max(self.peak, size)
            if size > self.maximum:
                raise IndexBuildError("INDEX_BUILD_QUOTA_EXCEEDED")
            self.callback({"stage": self.stage, "processed_records": self.records,
                           "total_records": self.total, "processed_bytes": None,
                           "total_bytes": None, "workspace_bytes": size,
                           "workspace_limit_bytes": self.maximum})
            self.last = now


def run_command(command, directory, guard, name):
    """No shell; output goes to bounded workspace files, heartbeat while waiting."""
    with (directory / (name + ".stdout")).open("wb") as out, (directory / (name + ".stderr")).open("wb") as err:
        process = subprocess.Popen(command, stdout=out, stderr=err)
        try:
            while process.poll() is None:
                guard.tick()
                time.sleep(.2)
            guard.tick(force=True)
            if process.returncode:
                raise IndexBuildError("INDEX_ENGINE_FAILED")
        except BaseException:
            process.kill()
            process.wait()
            raise


def _files(directory, guard):
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise IndexBuildError("INDEX_SYMLINK_REJECTED")
        if path.is_file():
            result.append({"name": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size,
                           "sha256": digest(path, guard.tick)})
    return result


def build(input_sqlite, output_dir, acquisition_manifest_sha256, progress_callback, *, max_temporary_bytes=MAX_TEMPORARY_BYTES):
    """Return small manifest and two artifacts: manifest.json and index.tar.

    Caller authenticates the fixed input object; this function verifies all source
    record/text hashes and index contents. Callback exceptions propagate unchanged.
    A failed attempt keeps diagnostic files but never produces a success manifest.
    """
    source, output = Path(input_sqlite).resolve(), Path(output_dir).resolve()
    if not re.fullmatch(r"[0-9a-f]{64}", acquisition_manifest_sha256):
        raise IndexBuildError("INDEX_INVALID_INPUT_IDENTITY")
    if not output.is_relative_to(ROOT / "tmp") or output.exists() or source.is_symlink() or not source.is_file():
        raise IndexBuildError("INDEX_INVALID_PATH")
    if type(max_temporary_bytes) is not int or not 0 < max_temporary_bytes <= MAX_TEMPORARY_BYTES:
        raise IndexBuildError("INDEX_INVALID_BUDGET")
    output.mkdir(parents=True)
    bundle, temporary = output / "bundle", output / "temporary"
    bundle.mkdir()
    temporary.mkdir()
    guard = Guard(output, source.stat().st_size, progress_callback, max_temporary_bytes)
    db = sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA cache_size=-16384")
    # Queries below use primary-key scans and indexed joins, never disk sorting.
    callback_error = []

    def sql_tick():
        try:
            guard.tick()
        except Exception as exc:  # noqa: BLE001 -- preserve original callback/fencing failure after SQLite abort
            callback_error.append(exc)
            return 1
        return 0

    db.set_progress_handler(sql_tick, 100_000)
    try:
        guard.tick(force=True)
        version = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "cwb"], capture_output=True, text=True, timeout=5, check=True).stdout
        if version != RECIPE["cwb_package"]:
            raise IndexBuildError("INDEX_ENGINE_VERSION_MISMATCH")
        if db.execute("SELECT value FROM metadata WHERE key='recipe'").fetchone() != ("tatoeba-full/v1",):
            # Exact parser recipe checked against the producer below; no guessed schemas.
            from pipelines.sources.tatoeba import RECIPE as INPUT_RECIPE
            if db.execute("SELECT value FROM metadata WHERE key='recipe'").fetchone() != (INPUT_RECIPE,):
                raise IndexBuildError("INDEX_INPUT_RECIPE_MISMATCH")
        count = db.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
        if not 0 < count <= LIMITS["sentences"]:
            raise IndexBuildError("INDEX_INPUT_LIMIT")
        guard.tick(total=count)
        input_sha = digest(source, guard.tick)
        tokenizer = SurfaceTokenizer(temporary)
        counts = {"sentences": count, "cmn_sentences": 0, "eng_sentences": 0, "characters": 0,
                  "tokens": 0, "direct_edges": 0, "unknown_owner": 0}
        vocabulary = Counter()
        token_hash, members_hash, metadata_hash = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
        with ((bundle / "texts.utf8").open("wb") as texts,
              (bundle / "records.map").open("wb") as records,
              (bundle / "tokens.map").open("wb") as tokens,
              (bundle / "members.jsonl").open("wb") as members,
              (bundle / "input.vrt").open("w", encoding="utf-8", newline="\n") as vrt):
            guard.tick(stage="TOKENIZING", records=0, force=True)
            for ordinal, row in enumerate(db.execute("SELECT id,language,text,owner,added,modified,record_hash,text_hash,source_line FROM sentences ORDER BY id")):
                sid, language, text, owner, added, modified, record_hash, text_hash, line = row
                if language not in ("cmn", "eng") or not 0 < len(text) <= LIMITS["sentence_characters"] or "\x00" in text:
                    raise IndexBuildError("INDEX_INVALID_SOURCE_RECORD")
                raw = text.encode("utf-8")
                if hashlib.sha256(raw).hexdigest() != text_hash or hashlib.sha256(encoded(row[:6])).hexdigest() != record_hash:
                    raise IndexBuildError("INDEX_INPUT_HASH_MISMATCH")
                spans = tokenizer.spans(text, language)
                if counts["tokens"] + len(spans) > LIMITS["tokens"] or counts["characters"] + len(text) > LIMITS["characters"]:
                    raise IndexBuildError("INDEX_INPUT_LIMIT")
                records.write(RECORD.pack(sid, texts.tell(), len(raw), counts["characters"], len(text), counts["tokens"]))
                texts.write(raw)
                vrt.write("<doc>\n<s>\n")
                local_hash = hashlib.sha256()
                for number, (start, end, form) in enumerate(spans):
                    tokens.write(TOKEN.pack(ordinal, start, end))
                    vrt.write(f"{number}\t{storage_key(form)}\n")
                    # Hash the exact cwb-decode -C -n stream independently of mapping storage.
                    token_hash.update(f"{counts['tokens']}\t{form}\n".encode())
                    counts["tokens"] += 1
                    local_hash.update(encoded([start, end, form]) + b"\n")
                vrt.write("</s>\n</doc>\n")
                meta = {"id": sid, "language": language, "owner": owner, "added": added, "modified": modified,
                        "source_line": line, "source_url": f"https://tatoeba.org/en/sentences/show/{sid}", "license": "CC-BY-2.0-FR"}
                metadata_hash.update(encoded(meta) + b"\n")
                member = {**meta, "ordinal": ordinal, "text_sha256": text_hash, "record_sha256": record_hash,
                          "token_sha256": local_hash.hexdigest(), "segment": [0, len(text)],
                          "revision_id": f"tatoeba:{sid}:{text_hash}", "source_map": "identity_codepoints"}
                line_bytes = encoded(member) + b"\n"
                members.write(line_bytes)
                members_hash.update(line_bytes)
                vocabulary.update(text)
                counts["characters"] += len(text)
                counts[language + "_sentences"] += 1
                counts["unknown_owner"] += owner is None
                if ordinal % 100 == 0:
                    guard.tick(records=ordinal + 1)
        with (bundle / "edges.tsv").open("w", encoding="ascii", newline="\n") as edges:
            invalid = db.execute("SELECT COUNT(*) FROM edges e LEFT JOIN sentences c ON c.id=e.cmn_id LEFT JOIN sentences n ON n.id=e.eng_id WHERE c.language IS NOT 'cmn' OR n.language IS NOT 'eng'").fetchone()[0]
            if invalid:
                raise IndexBuildError("INDEX_INVALID_EDGE")
            for left, right in db.execute("SELECT cmn_id,eng_id FROM edges ORDER BY cmn_id,eng_id"):
                edges.write(f"{left}\t{right}\n")
                counts["direct_edges"] += 1
                if counts["direct_edges"] % 10000 == 0:
                    guard.tick()
        guard.tick(stage="CHARACTER_INDEX", records=0)
        entries, cursors, offset = {}, {}, 0
        for char, frequency in sorted(vocabulary.items()):
            entries[char] = {"offset": offset, "count": frequency}
            cursors[char] = offset
            offset += frequency * 8
        if guard.peak + offset > max_temporary_bytes:
            raise IndexBuildError("INDEX_BUILD_QUOTA_EXCEEDED")
        postings = bundle / "characters.bin"
        with postings.open("w+b") as stream:
            stream.truncate(offset)
            with mmap.mmap(stream.fileno(), 0) as mapped:
                global_position = 0
                for ordinal, (text,) in enumerate(db.execute("SELECT text FROM sentences ORDER BY id")):
                    for character in text:
                        U64.pack_into(mapped, cursors[character], global_position)
                        cursors[character] += 8
                        global_position += 1
                    if ordinal % 1000 == 0:
                        guard.tick(records=ordinal + 1)
                mapped.flush()
        for char, entry in entries.items():
            if cursors[char] != entry["offset"] + entry["count"] * 8:
                raise IndexBuildError("INDEX_POSTING_COUNT_MISMATCH")
        (bundle / "characters.json").write_bytes(encoded(entries))
        guard.tick(stage="CWB_INDEX", records=0)
        data, registry = bundle / "data", bundle / "registry"
        data.mkdir()
        registry.mkdir()
        run_command(["cwb-encode", "-n", "-d", str(data), "-c", "utf8", "-f", str(bundle / "input.vrt"),
                     "-R", str(registry / "source"), "-S", "s", "-S", "doc"], temporary, guard, "encode")
        run_command(["cwb-makeall", "-r", str(registry), "-V", "SOURCE"], temporary, guard, "makeall")
        guard.tick(stage="VERIFYING", records=0, total=counts["tokens"])
        run_command(["cwb-decode", "-C", "-n", "-r", str(registry), "SOURCE", "-P", "word"], temporary, guard, "decode")
        decoded_hash = hashlib.sha256()
        decoded_count = 0
        with (temporary / "decode.stdout").open("r", encoding="ascii") as decoded:
            for line in decoded:
                position, key = line.rstrip("\n").split("\t")
                if position != str(decoded_count) or not re.fullmatch(r"u(?:[0-9a-f]{2})+", key):
                    raise IndexBuildError("INDEX_TOKEN_ROUNDTRIP_FAILED")
                form = bytes.fromhex(key[1:]).decode("utf-8")
                decoded_hash.update(f"{decoded_count}\t{form}\n".encode())
                decoded_count += 1
                if decoded_count % 10000 == 0:
                    guard.tick(records=decoded_count, total=counts["tokens"])
        if decoded_count != counts["tokens"] or decoded_hash.hexdigest() != token_hash.hexdigest():
            raise IndexBuildError("INDEX_TOKEN_ROUNDTRIP_FAILED")
        # Portable immutable registry template; reader materializes HOME only in its private runtime directory.
        registry_file = registry / "source"
        content = registry_file.read_text("utf-8")
        content, replacements = re.subn(r"(?m)^HOME\s+.*$", 'HOME "__INDEX_DATA__"', content)
        content = re.sub(r"(?m)^INFO\s+.*\n?", "", content)
        if replacements != 1:
            raise IndexBuildError("INDEX_REGISTRY_INVALID")
        registry_file.write_text(content, encoding="utf-8")
        # VRT is reproducible construction material; token roundtrip verified before removing it.
        (bundle / "input.vrt").unlink()
        files = _files(bundle, guard)
        identity = {"format": "source-index/v1", "recipe_sha256": RECIPE_SHA256,
                    "acquisition_manifest_sha256": acquisition_manifest_sha256, "input_sqlite_sha256": input_sha,
                    "ordered_members_sha256": members_hash.hexdigest(), "metadata_sha256": metadata_hash.hexdigest(),
                    "token_stream_sha256": token_hash.hexdigest(), "character_postings_sha256": next(f['sha256'] for f in files if f['name']=='characters.bin'),
                    "engine": {"character": "source-position/v1", "token": "CWB-3.5.0"}}
        manifest = {"format": "source-index/v1", "recipe": RECIPE, "recipe_id": RECIPE_ID, "recipe_sha256": RECIPE_SHA256,
                    "identity": identity, "identity_sha256": hashlib.sha256(encoded(identity)).hexdigest(), "counts": counts,
                    "quality": {"all_source_sentences_indexed": True, "rejected_sentences": 0, "token_roundtrip_verified": True,
                                "attributes": ["form"], "document_count_unit": "imported_sentence_record", "normalization": "none"},
                    "files": files, "stage": "INDEXED", "published": False, "query_ready": False}
        (bundle / "manifest.json").write_bytes(encoded(manifest))
        guard.tick(stage="PACKAGING", records=count, total=count)
        package = output / "index.tar"
        if sum(f["bytes"] for f in files) + len(encoded(manifest)) + (len(files) + 1) * 2048 > MAX_ARTIFACT_BYTES:
            raise IndexBuildError("INDEX_ARTIFACT_TOO_LARGE")
        with tarfile.open(package, "w") as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(bundle).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(info, _ProgressReader(stream, guard))
                    guard.tick(force=True)
        guard.tick(force=True)
        if package.stat().st_size > MAX_ARTIFACT_BYTES:
            raise IndexBuildError("INDEX_ARTIFACT_TOO_LARGE")
        package_sha = digest(package, guard.tick)
        final = {**manifest, "package": {"name": package.name, "bytes": package.stat().st_size, "sha256": package_sha},
                 "measurement": {"wall_seconds": time.monotonic() - guard.started, "sampled_peak_workspace_bytes_including_input": guard.peak,
                                 "peak_is_sampled": True, "max_temporary_bytes": max_temporary_bytes}}
        final_path = output / "manifest.json"
        final_path.write_bytes(encoded(final))
        return {"manifest": final, "manifest_path": final_path, "counts": counts,
                "artifacts": [{"name": p.name, "path": p, "bytes": p.stat().st_size, "sha256": digest(p, guard.tick)} for p in (package, final_path)]}
    except sqlite3.OperationalError:
        if callback_error:
            raise callback_error[0]
        raise
    finally:
        db.close()
