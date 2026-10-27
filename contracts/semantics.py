"""Small contract invariants, applied only after JSON Schema validation.

These helpers neither authorize access nor execute queries. Production APIs must
also check current permissions, reference ownership, engine capabilities and limits.
"""
import hashlib
import json


def scope_digest(scope):
    """Derived result references do not enlarge a fixed research scope."""
    identity = {key: value for key, value in scope.items() if key != 'result_refs'}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_query_semantics(query):
    def positive(pattern):
        if pattern['type'] != 'sequence':
            return
        items = pattern['items']
        if items[0]['type'] == 'gap' or items[-1]['type'] == 'gap':
            raise ValueError('QUERY_UNSUPPORTED: gaps require a positive match on both sides')
        previous_gap = False
        for item in items:
            is_gap = item['type'] == 'gap'
            if is_gap and (previous_gap or item['min'] > item['max']):
                raise ValueError('QUERY_UNSUPPORTED: invalid gap interval or consecutive gaps')
            previous_gap = is_gap

    pattern = query['pattern']
    if pattern['type'] == 'any_of':
        for branch in pattern['patterns']:
            positive(branch)
    else:
        positive(pattern)
    if 'condition' in query:
        positive(query['condition']['pattern'])


def validate_snapshot_members(snapshot, revisions, mounts):
    """Verify an already-typed fixture graph; not a replacement for DB constraints."""
    seen = set()
    for ordinal, member in enumerate(snapshot['members']):
        revision_id = member['material_revision_id']
        if member['ordinal'] != ordinal or revision_id in seen:
            raise ValueError('Snapshot members must be ordered and unique by actual revision')
        seen.add(revision_id)
        origin = revisions[revision_id]['origin']
        if origin['kind'] == 'private':
            if origin['project_id'] != snapshot['project_id'] or member['mount_id'] is not None:
                raise ValueError('Private revision belongs to another project or masquerades as a mount')
        else:
            mount = mounts[member['mount_id']]
            if mount['project_id'] != snapshot['project_id'] or mount['release_id'] != origin['release_id']:
                raise ValueError('Source revision requires matching project mount and release')


def validate_tool_result_semantics(result, invocation_id, action_id, operation_kind):
    """Bind an envelope to its host-assigned invocation and action ledger keys."""
    if result['invocation_id'] != invocation_id or result['action_id'] != action_id:
        raise ValueError('Tool result does not belong to the registered invocation/action')
    if operation_kind != 'read' and not action_id:
        raise ValueError('Writes and task submissions require a host-assigned action_id')
    if operation_kind == 'read' and action_id is not None:
        raise ValueError('Reads must not claim a write action_id')
    if result['status'] == 'unknown' and result['reconcile']['invocation_id'] != invocation_id:
        raise ValueError('Unknown outcome must reconcile the original invocation')


def validate_continuation_semantics(intent, registry):
    """Contract check only; host still checks authorization and cancellation."""
    actions = {entry['capability_id']: entry for entry in registry}
    for step in intent['steps']:
        entry = actions[step['capability_id']]
        if entry['availability']['status'] != 'available':
            raise ValueError('CAPABILITY_UNAVAILABLE: continuation action is planned')
        target = intent['target_scope']
        if target['scope_kind'] not in entry['scope_kind']:
            raise ValueError('SCOPE_INVALID: continuation action does not support target scope')
        if step['capability_id'] == 'corpus.search' and step['parameters']['snapshot_id'] not in target['snapshot_ids']:
            raise ValueError('ENDPOINT_OUT_OF_SCOPE: continuation query is outside target scope')
