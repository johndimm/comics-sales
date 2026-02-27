PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS comics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_row INTEGER,
  marvel_id TEXT,
  title TEXT NOT NULL,
  issue TEXT,
  issue_sort INTEGER,
  year INTEGER,
  publisher TEXT,
  genre TEXT,
  grade_raw TEXT,
  grade_numeric REAL,
  cgc_cert TEXT,
  qualified_flag INTEGER DEFAULT 0,
  community_url TEXT,
  artist TEXT,
  notes TEXT,
  status TEXT DEFAULT 'unlisted',
  target_price REAL,
  min_price REAL,
  sold_price REAL,
  sold_date TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_comics_title_issue ON comics(title, issue);
CREATE INDEX IF NOT EXISTS idx_comics_status ON comics(status);

CREATE TABLE IF NOT EXISTS market_comps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  comic_id INTEGER,
  source TEXT NOT NULL,
  listing_type TEXT CHECK(listing_type IN ('sold','active','offer')) NOT NULL,
  title TEXT,
  issue TEXT,
  grade_numeric REAL,
  grade_company TEXT,
  is_raw INTEGER DEFAULT 0,
  is_signed INTEGER DEFAULT 0,
  price REAL,
  shipping REAL DEFAULT 0,
  sold_date TEXT,
  url TEXT,
  match_score REAL,
  raw_payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(comic_id) REFERENCES comics(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_market_comps_comic ON market_comps(comic_id);
CREATE INDEX IF NOT EXISTS idx_market_comps_type_date ON market_comps(listing_type, sold_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_comps_dedupe
  ON market_comps(source, listing_type, title, IFNULL(issue,''), IFNULL(price,0), IFNULL(sold_date,''), IFNULL(url,''));

CREATE TABLE IF NOT EXISTS price_suggestions (
  comic_id INTEGER PRIMARY KEY,
  quick_sale REAL,
  market_price REAL,
  premium_price REAL,
  universal_market_price REAL,
  qualified_market_price REAL,
  confidence TEXT,
  basis_count INTEGER,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(comic_id) REFERENCES comics(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS price_suggestion_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  comic_id INTEGER NOT NULL,
  comp_id INTEGER NOT NULL,
  rank INTEGER,
  used_in_fmv INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(comic_id) REFERENCES comics(id) ON DELETE CASCADE,
  FOREIGN KEY(comp_id) REFERENCES market_comps(id) ON DELETE CASCADE,
  UNIQUE(comic_id, comp_id)
);

CREATE INDEX IF NOT EXISTS idx_pse_comic ON price_suggestion_evidence(comic_id, rank);