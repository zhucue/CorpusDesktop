import { DatabaseSync } from 'node:sqlite';

/** S0 local, durable concurrency experiment only. Production authority remains FastAPI/PostgreSQL. */
export class ExperimentalLeaseStore {
  private db: DatabaseSync;
  constructor(path: string) {
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS leases (session TEXT PRIMARY KEY, owner TEXT NOT NULL,
      epoch INTEGER NOT NULL, expires INTEGER NOT NULL, archive TEXT);`);
  }
  acquire(session: string, owner: string, now: number, ttl: number): number | null {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const existing = this.db.prepare('SELECT epoch, expires FROM leases WHERE session=?').get(session);
      if (existing && Number(existing.expires) > now) {
        this.db.exec('ROLLBACK');
        return null;
      }
      const epoch = existing ? Number(existing.epoch) + 1 : 1;
      this.db.prepare(`INSERT INTO leases(session, owner, epoch, expires) VALUES (?, ?, ?, ?)
        ON CONFLICT(session) DO UPDATE SET owner=excluded.owner, epoch=excluded.epoch, expires=excluded.expires`)
        .run(session, owner, epoch, now + ttl);
      this.db.exec('COMMIT');
      return epoch;
    } catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
  publish(session: string, owner: string, epoch: number, now: number, archive: string): boolean {
    return this.db.prepare('UPDATE leases SET archive=? WHERE session=? AND owner=? AND epoch=? AND expires>?')
      .run(archive, session, owner, epoch, now).changes === 1;
  }
  get(session: string) { return this.db.prepare('SELECT * FROM leases WHERE session=?').get(session); }
  close() { this.db.close(); }
}
