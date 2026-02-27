import Database from 'better-sqlite3';
import path from 'path';

let db: Database.Database | null = null;

export function getDb() {
  if (!db) {
    const p = process.env.COMICS_DB_PATH || path.resolve(process.cwd(), '../data/comics.db');
    db = new Database(p, { readonly: true });
  }
  return db;
}
