"""One bounded project index from fixed complete source and private revisions."""
import hashlib
import json
import mmap
import re
import sqlite3
import struct
import subprocess
import tarfile
import time
from collections import Counter
from pathlib import Path

from pipelines.materials.txt import RECIPE_SHA256 as TXT_RECIPE_SHA256
from pipelines.query.project_recipe import RECIPE, RECIPE_ID, RECIPE_SHA256
from pipelines.query.source_index import (
    LIMITS,
    MAX_ARTIFACT_BYTES,
    MAX_TEMPORARY_BYTES,
    RECORD,
    ROOT,
    TOKEN,
    U64,
    Guard,
    IndexBuildError,
    _files,
    _ProgressReader,
    digest,
    run_command,
)
from pipelines.query.source_recipe import SurfaceTokenizer, encoded, storage_key

META = struct.Struct('<QQ')


def _private(member, guard):
    directory = Path(member['directory']).resolve()
    manifest_path = directory/'manifest.json'
    if digest(manifest_path, guard.tick) != member['manifest_sha256']:
        raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
    manifest = json.loads(manifest_path.read_bytes())
    if manifest['format'] != 'private-txt/v1' or manifest['recipe_sha256'] != TXT_RECIPE_SHA256:
        raise IndexBuildError('INDEX_INPUT_RECIPE_MISMATCH')
    if {x['name'] for x in manifest['files']} != {'canonical.utf8','segments.jsonl'}:
        raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
    for entry in manifest['files']:
        path = directory/entry['name']
        if path.is_symlink() or path.stat().st_size != entry['bytes'] or digest(path,guard.tick) != entry['sha256']:
            raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
    return directory, manifest


def _inputs(members, guard):
    """Descriptors stay small. Source sentence documents are streamed, never listed."""
    from pipelines.query.source_reader import SourceIndexReader
    private_documents = {}
    prepared = []
    for member in members:
        if member['kind'] == 'private':
            directory, manifest = _private(member,guard)
            doc, rev = manifest['document_id'], manifest['revision_id']
            if doc in private_documents and private_documents[doc] != rev:
                raise IndexBuildError('DOCUMENT_REVISION_CONFLICT')
            private_documents[doc] = rev
            prepared.append(((1,doc,rev), member,directory,manifest))
        elif member['kind'] == 'source':
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',member['source_id']):
                raise IndexBuildError('INDEX_SOURCE_ID_INVALID')
            prepared.append(((0,member['source_id'],member['identity_sha256']),member,None,None))
        else:
            raise IndexBuildError('INDEX_INPUT_KIND_INVALID')
    for key,member,directory,manifest in sorted(prepared,key=lambda item:item[0]):
        if member['kind'] == 'private':
            meta={'document_id':manifest['document_id'],'revision_id':manifest['revision_id'],
                  'origin_kind':'private','source_id':None,'source_sentence_id':None,'source_url':None,
                  'language':manifest['language'],'canonical_sha256':next(x['sha256'] for x in manifest['files'] if x['name']=='canonical.utf8'),
                  'source_mapping':manifest['source_mapping'],'document_characters':manifest['counts']['characters']}
            def segments(directory=directory,manifest=manifest):
                cp=byte=ordinal=0
                with (directory/'canonical.utf8').open('rb') as text, (directory/'segments.jsonl').open('r',encoding='utf-8') as rows:
                    for line in rows:
                        row=json.loads(line)
                        if row['ordinal'] != ordinal or row['start_cp'] != cp or row['byte_start'] != byte or row['segment_id'] != f"{manifest['revision_id']}:s:{ordinal}":
                            raise IndexBuildError('INDEX_SEGMENT_MAPPING_INVALID')
                        raw=text.read(row['byte_end']-byte)
                        value=raw.decode('utf-8')
                        if len(value) != row['end_cp']-cp or len(raw) != row['byte_end']-byte:
                            raise IndexBuildError('INDEX_SEGMENT_MAPPING_INVALID')
                        yield row,value,None
                        cp,byte,ordinal=row['end_cp'],row['byte_end'],ordinal+1
                        guard.tick()
                    if text.read(1) or cp != manifest['counts']['characters'] or ordinal != manifest['counts']['segments']:
                        raise IndexBuildError('INDEX_SEGMENT_MAPPING_INVALID')
            yield 'private:'+manifest['revision_id'],meta,segments()
        else:
            directory=Path(member['directory']).resolve()
            if digest(directory/'manifest.json',guard.tick) != member['manifest_sha256']:
                raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
            # Full source cache was verified by the backend; validate each file again with cancellation.
            manifest=json.loads((directory/'manifest.json').read_bytes())
            for entry in manifest['files']:
                path=directory/entry['name']
                if not path.resolve().is_relative_to(directory) or path.is_symlink() or digest(path,guard.tick) != entry['sha256']:
                    raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
            with SourceIndexReader(directory,verify=False) as reader, (directory/'members.jsonl').open(encoding='utf-8') as rows:
                if reader.manifest['format'] != 'source-index/v1' or reader.manifest['identity_sha256'] != member['identity_sha256']:
                    raise IndexBuildError('INDEX_IDENTITY_MISMATCH')
                for ordinal,line in enumerate(rows):
                    old=json.loads(line);record=reader.record(ordinal);value=reader.text(ordinal)
                    if old['ordinal'] != ordinal or old['id'] != record[0] or old['text_sha256'] != hashlib.sha256(value.encode()).hexdigest():
                        raise IndexBuildError('INDEX_INPUT_HASH_MISMATCH')
                    end=reader.record(ordinal+1)[5] if ordinal+1 < reader.count else reader.manifest['counts']['tokens']
                    def token_spans(start=record[5],end=end,ordinal=ordinal,value=value):
                        for pos in range(start,end):
                            segment,a,b=TOKEN.unpack_from(reader.maps['tokens.map'],pos*TOKEN.size)
                            if segment != ordinal or not 0 <= a < b <= len(value):
                                raise IndexBuildError('INDEX_TOKEN_MAPPING_INVALID')
                            yield a,b,value[a:b]
                    meta={'document_id':f"source:{member['source_id']}:{old['id']}",
                          'revision_id':old['revision_id'],'origin_kind':'source','source_id':member['source_id'],
                          'source_sentence_id':old['id'],'source_url':old['source_url'],'language':old['language'],
                          'owner':old['owner'],'license':old['license'],'added':old.get('added'),'modified':old.get('modified'),
                          'source_line':old.get('source_line'),'record_sha256':old['record_sha256'],
                          'canonical_sha256':old['text_sha256'],'document_characters':len(value)}
                    row={'ordinal':0,'segment_id':old['revision_id']+':sentence','start_cp':0,'end_cp':len(value)}
                    yield member['source_id']+':'+old['revision_id'],meta,iter([(row,value,token_spans())])
                    guard.tick()
                if ordinal+1 != reader.count:
                    raise IndexBuildError('INDEX_INPUT_COUNT_MISMATCH')


def build_project(members, output_dir, snapshot_manifest_sha256, progress_callback, *, max_temporary_bytes=MAX_TEMPORARY_BYTES):
    output=Path(output_dir).resolve()
    if not members or len(members)>128 or not re.fullmatch('[0-9a-f]{64}',snapshot_manifest_sha256):
        raise IndexBuildError('INDEX_INVALID_INPUT_IDENTITY')
    if output.exists() or not output.is_relative_to(ROOT/'tmp') or not 0 < max_temporary_bytes <= MAX_TEMPORARY_BYTES:
        raise IndexBuildError('INDEX_INVALID_PATH')
    output.mkdir(parents=True);bundle=output/'bundle';temporary=output/'temporary';bundle.mkdir();temporary.mkdir()
    input_bytes=sum(sum(p.stat().st_size for p in Path(m['directory']).rglob('*') if p.is_file()) for m in members)
    guard=Guard(output,input_bytes,progress_callback,max_temporary_bytes)
    guard.tick(force=True)
    version=subprocess.run(['dpkg-query','-W','-f=${Version}','cwb'],capture_output=True,text=True,timeout=5,check=True).stdout
    if version != RECIPE['cwb_package']:
        raise IndexBuildError('INDEX_ENGINE_VERSION_MISMATCH')
    tokenizer=SurfaceTokenizer(temporary)
    seen=sqlite3.connect(temporary/'seen.sqlite3')
    seen.execute('CREATE TABLE revisions (identity TEXT PRIMARY KEY) WITHOUT ROWID')
    seen.execute('PRAGMA cache_size=-8192')
    counts={key:0 for key in ('documents','source_documents','private_documents','sentences','cmn_sentences','eng_sentences','characters','tokens','direct_edges','unknown_owner')}
    token_hash,members_hash=hashlib.sha256(),hashlib.sha256()
    vocabulary=Counter()
    try:
        with ((bundle/'texts.utf8').open('wb') as texts,(bundle/'records.map').open('wb') as records,
              (bundle/'tokens.map').open('wb') as tokens,(bundle/'members.jsonl').open('wb') as metadata,
              (bundle/'metadata.map').open('wb') as metadata_map,(bundle/'input.vrt').open('w',encoding='utf-8',newline='\n') as vrt):
            guard.tick(stage='TOKENIZING',records=0)
            for identity,meta,segments in _inputs(members,guard):
                if not seen.execute('INSERT OR IGNORE INTO revisions VALUES(?)',(identity,)).rowcount:
                    continue
                document=counts['documents'];counts['documents']+=1;counts[meta['origin_kind']+'_documents']+=1
                vrt.write('<doc>\n')
                for segment,value,existing_tokens in segments:
                    ordinal=counts['sentences'];language=meta['language'];raw=value.encode('utf-8')
                    if not value.strip() or len(value)>LIMITS['sentence_characters'] or '\x00' in value:
                        raise IndexBuildError('INDEX_INVALID_SOURCE_RECORD')
                    if counts['sentences']>=LIMITS['sentences'] or counts['characters']+len(value)>LIMITS['characters']:
                        raise IndexBuildError('INDEX_INPUT_LIMIT')
                    records.write(RECORD.pack(document,texts.tell(),len(raw),counts['characters'],len(value),counts['tokens']))
                    texts.write(raw);vrt.write('<s>\n');local_hash=hashlib.sha256();token_start=counts['tokens'];cursor=0
                    for number,(start,end,form) in enumerate(existing_tokens if existing_tokens is not None else tokenizer.spans(value,language)):
                        if not 0 <= cursor <= start < end <= len(value) or value[cursor:start].strip() or form != value[start:end]:
                            raise IndexBuildError('INDEX_TOKEN_MAPPING_INVALID')
                        tokens.write(TOKEN.pack(ordinal,start,end));vrt.write(f'{number}\t{storage_key(form)}\n')
                        token_hash.update(f"{counts['tokens']}\t{form}\n".encode());counts['tokens']+=1;cursor=end
                        local_hash.update(encoded([start,end,form])+b'\n')
                    if value[cursor:].strip() or token_start==counts['tokens'] or counts['tokens']>LIMITS['tokens']:
                        raise IndexBuildError('INDEX_TOKEN_MAPPING_INVALID')
                    vrt.write('</s>\n')
                    entry={**meta,'ordinal':ordinal,'document_ordinal':document,'segment_id':segment['segment_id'],
                           'segment_start_cp':segment['start_cp'],'segment_end_cp':segment['end_cp'],
                           'text_sha256':hashlib.sha256(raw).hexdigest(),'token_sha256':local_hash.hexdigest()}
                    data=encoded(entry)+b'\n';metadata_map.write(META.pack(metadata.tell(),len(data)));metadata.write(data);members_hash.update(data)
                    vocabulary.update(value);counts['sentences']+=1;counts['characters']+=len(value);counts[language+'_sentences']+=1
                    counts['unknown_owner']+=meta['origin_kind']=='source' and meta.get('owner') is None
                    guard.tick(records=counts['sentences'])
                vrt.write('</doc>\n')
        seen.commit()
    finally:
        seen.close()
    if not counts['sentences']:
        raise IndexBuildError('INDEX_EMPTY')
    # Preserve fixed shared edge data separately with its source namespace.
    unique_sources=set()
    with (bundle/'edges.jsonl').open('wb') as edges:
        for member in sorted((m for m in members if m['kind']=='source'),key=lambda m:(m['source_id'],m['identity_sha256'])):
            key=(member['source_id'],member['identity_sha256'])
            if key in unique_sources:continue
            unique_sources.add(key)
            with (Path(member['directory'])/'edges.tsv').open('r',encoding='ascii') as rows:
                for row in rows:
                    left,right=map(int,row.split())
                    edges.write(encoded({'source_id':key[0],'source_index_identity':key[1],'left_source_id':left,'right_source_id':right})+b'\n')
                    counts['direct_edges']+=1;guard.tick()
    guard.tick(stage='CHARACTER_INDEX',records=0,total=counts['sentences'])
    entries={};cursors={};offset=0
    for char,frequency in sorted(vocabulary.items()):
        entries[char]={'offset':offset,'count':frequency};cursors[char]=offset;offset+=frequency*8
    if guard.peak+offset>max_temporary_bytes:raise IndexBuildError('INDEX_BUILD_QUOTA_EXCEEDED')
    with (bundle/'characters.bin').open('w+b') as stream, (bundle/'texts.utf8').open('rb') as text, (bundle/'records.map').open('rb') as records:
        stream.truncate(offset)
        with mmap.mmap(stream.fileno(),0) as mapped:
            position=0
            for ordinal in range(counts['sentences']):
                _,_,size,*_=RECORD.unpack(records.read(RECORD.size))
                for char in text.read(size).decode('utf-8'):
                    U64.pack_into(mapped,cursors[char],position);cursors[char]+=8;position+=1
                guard.tick(records=ordinal+1)
            mapped.flush()
    (bundle/'characters.json').write_bytes(encoded(entries))
    return _finish(bundle,temporary,output,counts,token_hash.hexdigest(),members_hash.hexdigest(),snapshot_manifest_sha256,guard)


def _finish(bundle, temporary, output, counts, token_digest, member_digest, snapshot_sha, guard):
    guard.tick(stage='CWB_INDEX',records=0)
    data,registry=bundle/'data',bundle/'registry';data.mkdir();registry.mkdir()
    run_command(['cwb-encode','-n','-d',str(data),'-c','utf8','-f',str(bundle/'input.vrt'),'-R',str(registry/'source'),'-S','s','-S','doc'],temporary,guard,'encode')
    run_command(['cwb-makeall','-r',str(registry),'-V','SOURCE'],temporary,guard,'makeall')
    guard.tick(stage='VERIFYING',records=0,total=counts['tokens'])
    run_command(['cwb-decode','-C','-n','-r',str(registry),'SOURCE','-P','word'],temporary,guard,'decode')
    h=hashlib.sha256();n=0
    with (temporary/'decode.stdout').open(encoding='ascii') as rows:
        for row in rows:
            position,key=row.rstrip('\n').split('\t')
            if position!=str(n) or not re.fullmatch(r'u(?:[0-9a-f]{2})+',key):raise IndexBuildError('INDEX_TOKEN_ROUNDTRIP_FAILED')
            h.update(f"{n}\t{bytes.fromhex(key[1:]).decode('utf-8')}\n".encode());n+=1;guard.tick(records=n)
    if n!=counts['tokens'] or h.hexdigest()!=token_digest:raise IndexBuildError('INDEX_TOKEN_ROUNDTRIP_FAILED')
    content=(registry/'source').read_text('utf-8');content,num=re.subn(r'(?m)^HOME\s+.*$','HOME "__INDEX_DATA__"',content)
    if num!=1:raise IndexBuildError('INDEX_REGISTRY_INVALID')
    (registry/'source').write_text(re.sub(r'(?m)^INFO\s+.*\n?','',content),encoding='utf-8');(bundle/'input.vrt').unlink()
    files=_files(bundle,guard)
    identity={'format':'project-index/v1','recipe_sha256':RECIPE_SHA256,'snapshot_manifest_sha256':snapshot_sha,
              'ordered_members_sha256':member_digest,'token_stream_sha256':token_digest,
              'files_sha256':hashlib.sha256(encoded(files)).hexdigest(),'engine':{'character':'source-position/v1','token':'CWB-3.5.0'}}
    manifest={'format':'project-index/v1','recipe':RECIPE,'recipe_id':RECIPE_ID,'recipe_sha256':RECIPE_SHA256,
              'identity':identity,'identity_sha256':hashlib.sha256(encoded(identity)).hexdigest(),'counts':counts,
              'quality':{'all_input_segments_indexed':True,'rejected_segments':0,'token_roundtrip_verified':True,'attributes':['form'],
                         'document_count_unit':'document','normalization':'none'},'files':files,'stage':'INDEXED','published':False,'query_ready':False}
    (bundle/'manifest.json').write_bytes(encoded(manifest));guard.tick(stage='PACKAGING',records=counts['sentences'],total=counts['sentences'])
    if sum(f['bytes'] for f in files)+len(encoded(manifest))+(len(files)+1)*2048>MAX_ARTIFACT_BYTES:raise IndexBuildError('INDEX_ARTIFACT_TOO_LARGE')
    package=output/'index.tar'
    with tarfile.open(package,'w') as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                info=archive.gettarinfo(str(path),arcname=path.relative_to(bundle).as_posix());info.mtime=info.uid=info.gid=0;info.uname=info.gname=''
                with path.open('rb') as stream:archive.addfile(info,_ProgressReader(stream,guard))
                guard.tick(force=True)
    if package.stat().st_size>MAX_ARTIFACT_BYTES:raise IndexBuildError('INDEX_ARTIFACT_TOO_LARGE')
    final={**manifest,'package':{'name':'index.tar','bytes':package.stat().st_size,'sha256':digest(package,guard.tick)},
           'measurement':{'wall_seconds':time.monotonic()-guard.started,'sampled_peak_workspace_bytes_including_input':guard.peak,'peak_is_sampled':True,'max_temporary_bytes':guard.maximum}}
    path=output/'manifest.json';path.write_bytes(encoded(final))
    return {'manifest':final,'manifest_path':path,'counts':counts,'artifacts':[{'name':p.name,'path':p,'bytes':p.stat().st_size,'sha256':digest(p,guard.tick)} for p in (package,path)]}
