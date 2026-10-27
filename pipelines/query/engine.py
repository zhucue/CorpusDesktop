"""S0 exact-query prototype over immutable, already segmented fixture revisions.

Character postings are compact unsigned integer arrays in Unicode codepoint
coordinates. Token postings use supplied token attributes, never inferred POS.
This is an experimental in-process engine, not a production authorization boundary.
"""
import json
from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from heapq import nsmallest
from pathlib import Path

from contracts.semantics import validate_query_semantics


class QueryError(ValueError):
    pass


@dataclass(slots=True)
class Revision:
    revision_id: str
    text: str
    sentences: list
    paragraphs: list
    tokens: list
    metadata: dict

    @classmethod
    def from_dict(cls, value):
        revision = cls(**value)
        for ranges in (revision.sentences, revision.paragraphs):
            previous = 0
            for start,end in ranges:
                if not 0 <= previous <= start < end <= len(revision.text):
                    raise ValueError('Invalid or overlapping canonical-text segment')
                previous = end
        previous = 0
        for token in revision.tokens:
            if not 0 <= previous <= token['start'] < token['end'] <= len(revision.text):
                raise ValueError('Invalid or overlapping token coordinates')
            if token['attrs']['form'] != revision.text[token['start']:token['end']]:
                raise ValueError('Token form does not match canonical text')
            previous = token['end']
        return revision


class PositionIndex:
    def __init__(self, revisions):
        self.revisions = []
        self.offsets = []
        self.char_postings = {}
        self.token_postings = {}
        self.token_offsets = []
        self.attributes = None
        self.revision_attributes = []
        self.segment_ranges = []
        self.sentence_bounds = []
        char_offset = token_offset = 0
        seen = set()
        for value in revisions:
            revision = value if isinstance(value, Revision) else Revision.from_dict(value)
            if revision.revision_id in seen:
                raise ValueError('Duplicate actual revision in snapshot')
            seen.add(revision.revision_id)
            self.revisions.append(revision)
            sentences = tuple(tuple(r) for r in revision.sentences)
            paragraphs = tuple(tuple(r) for r in revision.paragraphs)
            self.segment_ranges.append({'sentence':sentences,'paragraph':paragraphs})
            self.sentence_bounds.append((tuple(r[0] for r in sentences),tuple(r[1] for r in sentences)))
            self.offsets.append(char_offset)
            self.token_offsets.append(token_offset)
            revision_attrs = None
            for position,char in enumerate(revision.text, char_offset):
                self.char_postings.setdefault(char, array('Q')).append(position)
            for position,token in enumerate(revision.tokens, token_offset):
                keys = set(token['attrs'])
                revision_attrs = keys if revision_attrs is None else revision_attrs & keys
                self.attributes = keys if self.attributes is None else self.attributes & keys
                for attr,value in token['attrs'].items():
                    self.token_postings.setdefault((attr,value), array('Q')).append(position)
            self.revision_attributes.append(revision_attrs or set())
            char_offset += len(revision.text)
            token_offset += len(revision.tokens)
        self.attributes = self.attributes or {'form'}
        self.character_count = char_offset
        self.token_count = token_offset
        from jsonschema import Draft202012Validator
        schema = json.loads((Path(__file__).resolve().parents[2]/'contracts/schemas/corpus-query.schema.json').read_text(encoding='utf-8'))
        self.validator = Draft202012Validator(schema)

    def save(self, directory):
        """Persist inspectable corpus/mapping and raw integer postings; no pickle."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory/'revisions.jsonl').open('w',encoding='utf-8') as stream:
            for r in self.revisions:
                stream.write(json.dumps({name:getattr(r,name) for name in Revision.__slots__},ensure_ascii=False,separators=(',',':'))+'\n')
        vocabulary = []
        with (directory/'postings.bin').open('wb') as stream:
            for kind, postings in [('character',self.char_postings),('token',self.token_postings)]:
                for key, positions in postings.items():
                    vocabulary.append({'kind':kind,'key':key,'byte_offset':stream.tell(),'count':len(positions)})
                    # Portable little endian, even when built on a big-endian machine.
                    import sys
                    values = positions if sys.byteorder == 'little' else array('Q',positions)
                    if sys.byteorder != 'little': values.byteswap()
                    values.tofile(stream)
        (directory/'vocabulary.json').write_text(json.dumps(vocabulary,ensure_ascii=False),encoding='utf-8')

    @staticmethod
    def _within(span, ranges):
        start,end = span
        i = bisect_right(ranges,(start, float('inf'))) - 1
        if i >= 0 and ranges[i][0] <= start and end <= ranges[i][1]:
            return i
        return None

    def execute(self, query, page_size=50):
        from jsonschema import ValidationError
        try:
            self.validator.validate(query)
            validate_query_semantics(query)
        except (ValueError, ValidationError) as error:
            raise QueryError('QUERY_UNSUPPORTED: '+str(error)) from error
        # Validate capabilities before finding zero matches; unsupported queries never look empty.
        selected = [i for i,r in enumerate(self.revisions) if not any(
            r.metadata.get(key) not in values for key,values in query.get('filters',{}).items())]
        available = None
        for i in selected:
            if self.revisions[i].tokens:
                available = self.revision_attributes[i].copy() if available is None else available & self.revision_attributes[i]
        available = self.attributes if available is None else available
        def validate(pattern):
            if pattern['type'] == 'term':
                if pattern['op'] != 'eq': raise QueryError('QUERY_UNSUPPORTED: regex is not validated in S0')
                if pattern['attr'] not in available: raise QueryError('ATTRIBUTE_UNAVAILABLE: '+pattern['attr'])
            for item in pattern.get('items',pattern.get('patterns',[])): validate(item)
        validate(query['pattern'])
        if 'condition' in query: validate(query['condition']['pattern'])
        total = segments = documents = 0
        hits = []
        for ordinal in selected:
            revision = self.revisions[ordinal]
            sentence_ranges = self.segment_ranges[ordinal]['sentence']
            ranges = self.segment_ranges[ordinal][query['within']]
            matches = self._pattern(query['pattern'],query['unit'],ordinal)
            if query['unit'] == 'token':
                matches = {(revision.tokens[start]['start'],revision.tokens[end-1]['end']) for start,end in matches}
            # Patterns cannot leave this revision. A full-text segment therefore
            # needs no per-hit containment lookup, regardless of corpus contents.
            if ranges != ((0,len(revision.text)),):
                matches = {span for span in matches if self._within(span,ranges) is not None}
            condition = query.get('condition')
            if condition:
                cranges = self.segment_ranges[ordinal][condition['within']]
                other = self._pattern(condition['pattern'],query['unit'],ordinal)
                if query['unit'] == 'token':
                    other = {(revision.tokens[start]['start'],revision.tokens[end-1]['end']) for start,end in other}
                occupied = {self._within(span,cranges) for span in other} - {None}
                matches = {span for span in matches if (segment := self._within(span,cranges)) is not None and
                    ((segment in occupied) == (condition['operator'] == 'and'))}
            if matches:
                documents += 1
                # Segment counts are sentence counts, even for paragraph-scoped queries.
                if sentence_ranges == ((0,len(revision.text)),):
                    segments += 1
                else:
                    starts,ends = self.sentence_bounds[ordinal]
                    touched = set()
                    for start,end in matches:
                        touched.update(range(bisect_right(ends,start),bisect_left(starts,end)))
                    segments += len(touched)
                total += len(matches)
                remaining = page_size-len(hits)
                if remaining > 0:
                    for start,end in nsmallest(remaining,matches):
                        hits.append({'revision_id':revision.revision_id,'document_ordinal':ordinal,'start':start,'end':end})
        return {'total_hits':total,'matched_segments':segments,'matched_documents':documents,
                'counting_unit':'unique_revision_span','complete':True,'hits':hits}

    def _pattern(self, pattern, unit, ordinal):
        revision = self.revisions[ordinal]
        if pattern['type'] == 'any_of':
            return set().union(*(self._pattern(p,unit,ordinal) for p in pattern['patterns']))
        if pattern['type'] in ('literal','term'):
            value = pattern['value']
            offset = self.offsets[ordinal] if unit == 'character' else self.token_offsets[ordinal]
            limit = offset + (len(revision.text) if unit == 'character' else len(revision.tokens))
            posting = (self.char_postings.get(value[0],()) if unit == 'character' else
                       self.token_postings.get((pattern['attr'],value),()))
            positions = posting[bisect_left(posting,offset):bisect_left(posting,limit)]
            if unit == 'token' or len(value) == 1:
                return {(p-offset,p-offset+1) for p in positions}
            return {(p-offset,p-offset+len(value)) for p in positions if revision.text.startswith(value,p-offset)}
        items = pattern['items']
        spans = self._pattern(items[0],unit,ordinal)
        gap = (0,0)
        for item in items[1:]:
            if item['type'] == 'gap':
                gap = (item['min'],item['max'])
                continue
            following = sorted(self._pattern(item,unit,ordinal))
            starts = [start for start,end in following]
            joined = set()
            for first,last in spans:
                for start,end in following[bisect_left(starts,last+gap[0]):bisect_right(starts,last+gap[1])]:
                    joined.add((first,end))
            spans = joined
            gap = (0,0)
        return spans
