/** agent_sessions / agent_messages persistence (contracts/p2.md §六, migration 0002 owned by the api). */
import pg from 'pg';
import type { Message, PageContext, Part, Scope, Session, ToolCall } from './types.ts';

export interface SessionRecord extends Session { pi_session_path: string }

export interface MessageFields { content: string; parts: Part[]; tool_calls: ToolCall[]; duration_ms?: number | null; stopped?: boolean }

/** agent_messages has no flag or context column: a stopped run keeps a trailing {type: "stopped"} marker in
 * parts, a user message sent from a page a {type: "context", context} marker; both are stripped on read. */
const STOPPED = { type: 'stopped' };
const CONTEXT = 'context';
const storedParts = (parts: Part[], stopped?: boolean, context?: PageContext) =>
  JSON.stringify([...parts, ...(context ? [{ type: CONTEXT, context }] : []), ...(stopped ? [STOPPED] : [])]);

export interface Store {
  /** Process start: no run survives a restart (no cross-process resume). */
  resetRunning(): Promise<void>;
  createSession(session: Omit<SessionRecord, 'message_count' | 'created_at' | 'updated_at'>): Promise<SessionRecord>;
  getSession(id: string): Promise<SessionRecord | null>;
  listSessions(projectId: string, ownerId: string): Promise<SessionRecord[]>;
  updateSession(id: string, fields: { title?: string; scope?: Scope; state?: Session['state'] }): Promise<void>;
  deleteSession(id: string): Promise<void>;
  listMessages(sessionId: string): Promise<Message[]>;
  insertMessage(sessionId: string, message: Message): Promise<void>;
  updateMessage(id: string, fields: MessageFields): Promise<void>;
  deleteMessage(id: string): Promise<void>;
  /** One llm_usage row per model call (contracts/p9.md §二); a store without the table skips it. */
  recordUsage?(row: UsageRow): Promise<void>;
  /** Sum of the user's total_tokens since `since` (start of the current month). */
  monthlyTokens?(userId: string, since: Date): Promise<number>;
  close(): Promise<void>;
}

export interface UsageRow {
  user_id: string; project_id: string; session_id: string; source: 'agent' | 'agent:estimated'; model: string;
  prompt_tokens: number; completion_tokens: number; total_tokens: number;
}

const jsonOrNull = (value: unknown) => (value === null || value === undefined ? null : JSON.stringify(value));
const iso = (value: Date | string) => (value instanceof Date ? value.toISOString() : value);

function sessionRow(row: any): SessionRecord {
  return {
    id: row.id, project_id: row.project_id, owner_id: row.owner_id, title: row.title, scope: row.scope ?? null,
    state: row.state, created_at: iso(row.created_at), updated_at: iso(row.updated_at),
    message_count: Number(row.message_count ?? 0), pi_session_path: row.pi_session_path,
  };
}

function messageRow(row: any): Message {
  const raw: any[] = row.parts ?? [];
  const stopped = raw.some(part => part?.type === STOPPED.type);
  const context = raw.find(part => part?.type === CONTEXT)?.context;
  return {
    id: row.id, role: row.role, content: row.content ?? '',
    parts: raw.filter(part => part?.type !== STOPPED.type && part?.type !== CONTEXT),
    tool_calls: row.tool_calls ?? [], created_at: iso(row.created_at), duration_ms: row.duration_ms ?? null,
    ...(stopped ? { stopped: true } : {}),
    ...(context ? { context } : {}),
  };
}

const SESSION_COLUMNS = `s.id, s.project_id, s.owner_id, s.title, s.scope, s.state, s.pi_session_path, s.created_at, s.updated_at,
  (SELECT count(*) FROM agent_messages m WHERE m.session_id = s.id) AS message_count`;

export class PgStore implements Store {
  readonly pool: pg.Pool;
  constructor(databaseUrl: string) {
    this.pool = new pg.Pool({ connectionString: databaseUrl, max: 5 });
  }

  async resetRunning() {
    await this.pool.query(`UPDATE agent_sessions SET state = 'idle' WHERE state = 'running'`);
  }

  async createSession(session: Omit<SessionRecord, 'message_count' | 'created_at' | 'updated_at'>) {
    await this.pool.query(
      `INSERT INTO agent_sessions (id, project_id, owner_id, title, scope, state, pi_session_path, created_at, updated_at)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, now(), now())`,
      [session.id, session.project_id, session.owner_id, session.title, jsonOrNull(session.scope), session.state, session.pi_session_path],
    );
    return (await this.getSession(session.id))!;
  }

  async getSession(id: string) {
    const { rows } = await this.pool.query(`SELECT ${SESSION_COLUMNS} FROM agent_sessions s WHERE s.id = $1`, [id]);
    return rows[0] ? sessionRow(rows[0]) : null;
  }

  async listSessions(projectId: string, ownerId: string) {
    const { rows } = await this.pool.query(
      // A soft-deleted project lists no sessions (contracts/p9.md §五).
      `SELECT ${SESSION_COLUMNS} FROM agent_sessions s WHERE s.project_id = $1 AND s.owner_id = $2
         AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = s.project_id AND p.deleted_at IS NOT NULL)
       ORDER BY s.updated_at DESC`,
      [projectId, ownerId],
    );
    return rows.map(sessionRow);
  }

  async updateSession(id: string, fields: { title?: string; scope?: Scope; state?: Session['state'] }) {
    const sets: string[] = [];
    const values: unknown[] = [id];
    if (fields.title !== undefined) { values.push(fields.title); sets.push(`title = $${values.length}`); }
    if (fields.scope !== undefined) { values.push(jsonOrNull(fields.scope)); sets.push(`scope = $${values.length}::jsonb`); }
    if (fields.state !== undefined) { values.push(fields.state); sets.push(`state = $${values.length}`); }
    sets.push('updated_at = now()');
    await this.pool.query(`UPDATE agent_sessions SET ${sets.join(', ')} WHERE id = $1`, values);
  }

  async deleteSession(id: string) {
    // agent_messages.session_id is ON DELETE CASCADE
    await this.pool.query('DELETE FROM agent_sessions WHERE id = $1', [id]);
  }

  async listMessages(sessionId: string) {
    const { rows } = await this.pool.query(
      `SELECT id, role, content, parts, tool_calls, created_at, duration_ms FROM agent_messages
       WHERE session_id = $1 ORDER BY created_at, id`, [sessionId]);
    return rows.map(messageRow);
  }

  async insertMessage(sessionId: string, message: Message) {
    await this.pool.query(
      `INSERT INTO agent_messages (id, session_id, role, content, parts, tool_calls, created_at, duration_ms)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)`,
      [message.id, sessionId, message.role, message.content, storedParts(message.parts, message.stopped, message.context),
        JSON.stringify(message.tool_calls), message.created_at, message.duration_ms ?? null],
    );
  }

  async updateMessage(id: string, fields: MessageFields) {
    await this.pool.query(
      `UPDATE agent_messages SET content = $2, parts = $3::jsonb, tool_calls = $4::jsonb, duration_ms = $5 WHERE id = $1`,
      [id, fields.content, storedParts(fields.parts, fields.stopped), JSON.stringify(fields.tool_calls), fields.duration_ms ?? null],
    );
  }

  async deleteMessage(id: string) {
    await this.pool.query('DELETE FROM agent_messages WHERE id = $1', [id]);
  }

  async recordUsage(row: UsageRow) {
    await this.pool.query(
      `INSERT INTO llm_usage (user_id, project_id, session_id, source, model, prompt_tokens, completion_tokens, total_tokens)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [row.user_id, row.project_id, row.session_id, row.source, row.model, row.prompt_tokens, row.completion_tokens, row.total_tokens],
    );
  }

  async monthlyTokens(userId: string, since: Date) {
    const { rows } = await this.pool.query(
      'SELECT coalesce(sum(total_tokens), 0)::bigint AS total FROM llm_usage WHERE user_id = $1 AND created_at >= $2',
      [userId, since],
    );
    return Number(rows[0].total);
  }

  async close() { await this.pool.end(); }
}
