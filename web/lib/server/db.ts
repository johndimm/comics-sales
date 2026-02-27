import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

let db: Database.Database | null = null;

function resolveDbPath() {
  if (process.env.COMICS_DB_PATH && process.env.COMICS_DB_PATH.trim()) {
    return path.resolve(process.env.COMICS_DB_PATH);
  }

  const candidates = [
    path.resolve(process.cwd(), 'data/comics.db'),
    path.resolve(process.cwd(), '../data/comics.db'),
    path.resolve(__dirname, '../../data/comics.db'),
  ];

  const found = candidates.find((p) => fs.existsSync(p));
  if (found) return found;

  throw new Error(
    `COMICS DB not found. Set COMICS_DB_PATH or place comics.db at one of: ${candidates.join(', ')}`
  );
}

export function getDb() {
  if (!db) {
    const p = resolveDbPath();
    db = new Database(p, { readonly: true });
  }
  return db;
}
