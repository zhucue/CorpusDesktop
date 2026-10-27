/** Immutable API archive -> isolated working copy -> supported Pi SessionManager. */
import { createHash } from 'node:crypto';
import { copyFileSync, constants, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { CURRENT_SESSION_VERSION, SessionManager } from '@earendil-works/pi-coding-agent';
import { RUNTIME_MANIFEST, type RuntimeManifest, type Checkpoint, type CheckpointDownload, type Grant } from './s1-run-client.ts';

export function assertRuntime(grant: Grant, expected: RuntimeManifest = RUNTIME_MANIFEST) {
  if (!isDeepStrictEqual(grant.runtime_manifest, expected) || CURRENT_SESSION_VERSION !== 3) {
    throw new Error('CHECKPOINT_RUNTIME_MISMATCH');
  }
}

export function verifyArchive(checkpoint: Checkpoint, archive: string, expected: RuntimeManifest = RUNTIME_MANIFEST) {
  const bytes = Buffer.from(archive, 'utf8');
  if (bytes.length > 8 * 1024 * 1024 || bytes.length !== checkpoint.byte_size ||
      createHash('sha256').update(bytes).digest('hex') !== checkpoint.sha256) throw new Error('CHECKPOINT_DIGEST_MISMATCH');
  if (!isDeepStrictEqual(checkpoint.runtime_manifest, expected)) throw new Error('CHECKPOINT_RUNTIME_MISMATCH');
  // Pi's parser tolerates malformed lines. Check strict JSONL before opening so a
  // truncated or corrupt file cannot silently become a different conversation.
  const entries = archive.trimEnd().split('\n').map(line => JSON.parse(line));
  if (entries[0]?.type !== 'session' || entries[0].version !== 3 || entries[0].id !== checkpoint.sdk_session_id ||
      entries.at(-1)?.id !== checkpoint.leaf_id) throw new Error('CHECKPOINT_IDENTITY_MISMATCH');
  let parent: string | null = null;
  const ids = new Set<string>();
  for (const entry of entries.slice(1)) {
    if (!['model_change', 'thinking_level_change', 'message'].includes(entry.type) ||
        typeof entry.id !== 'string' || ids.has(entry.id) || entry.parentId !== parent) throw new Error('CHECKPOINT_NOT_LINEAR');
    ids.add(entry.id); parent = entry.id;
  }
  const last = entries.at(-1);
  if (last?.type !== 'message' || last.message?.role !== 'assistant' || last.message.stopReason !== 'stop') {
    throw new Error('CHECKPOINT_NOT_COMPLETE');
  }
  return bytes;
}

export function openCheckpoint(grant: Grant, downloaded: CheckpointDownload, directory: string, expected: RuntimeManifest = RUNTIME_MANIFEST) {
  assertRuntime(grant, expected);
  const effective = grant.resume_checkpoint ?? grant.base_checkpoint;
  if (!isDeepStrictEqual(downloaded.checkpoint, effective)) throw new Error('CHECKPOINT_BASE_MISMATCH');
  mkdirSync(directory, { recursive: true });
  const sessions = join(directory, 'sessions');
  if (!effective) {
    if (downloaded.session_jsonl !== null) throw new Error('CHECKPOINT_BASE_MISMATCH');
    return { manager: SessionManager.create(directory, sessions, { id: grant.session_id }), restored: false,
      immutablePath: undefined as string | undefined };
  }
  if (typeof downloaded.session_jsonl !== 'string') throw new Error('CHECKPOINT_MISSING');
  const bytes = verifyArchive(effective, downloaded.session_jsonl, expected);
  const immutablePath = join(directory, 'base-checkpoint.jsonl');
  const workingPath = join(directory, 'working-session.jsonl');
  writeFileSync(immutablePath, bytes, { flag: 'wx', mode: 0o600, flush: true });
  copyFileSync(immutablePath, workingPath, constants.COPYFILE_EXCL);
  // open() may migrate or append. It never receives the downloaded archive path.
  const manager = SessionManager.open(workingPath, sessions, directory);
  if (manager.getSessionId() !== effective.sdk_session_id || manager.getLeafId() !== effective.leaf_id) {
    throw new Error('CHECKPOINT_RESTORE_MISMATCH');
  }
  return { manager, restored: true, immutablePath };
}

export function sessionArchive(manager: SessionManager) {
  const file = manager.getSessionFile();
  if (!file || !manager.isPersisted()) throw new Error('CHECKPOINT_MISSING');
  return readFileSync(file, 'utf8');
}
