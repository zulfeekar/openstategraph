#!/usr/bin/env python3
"""Synthetic page-analytics SQLite — six related tables, FKs as JOIN rules.

The user's 6-tables-with-business-rules scenario, made concrete: pages,
referrers, experiments, sessions, pageviews, revenue. Deterministic seed,
internally consistent (revenue rows join to real sessions; pageviews to real
pages/sessions), sized for sub-second queries.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "workflows/page-analytics/data/analytics.sqlite"

SCHEMA = """
CREATE TABLE pages (
  page_id INTEGER PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL,
  section TEXT NOT NULL, published_on TEXT NOT NULL, author TEXT NOT NULL,
  word_count INTEGER NOT NULL, is_landing INTEGER NOT NULL,
  funnel_step INTEGER, canonical_page_id INTEGER REFERENCES pages(page_id)
);
CREATE TABLE referrers (
  referrer_id INTEGER PRIMARY KEY, domain TEXT NOT NULL, medium TEXT NOT NULL,
  campaign TEXT, is_paid INTEGER NOT NULL, first_seen TEXT NOT NULL,
  quality_score REAL NOT NULL, country TEXT NOT NULL, partner_tier TEXT,
  notes TEXT
);
CREATE TABLE experiments (
  experiment_id INTEGER PRIMARY KEY, name TEXT NOT NULL, hypothesis TEXT NOT NULL,
  started_on TEXT NOT NULL, ended_on TEXT, primary_metric TEXT NOT NULL,
  owner TEXT NOT NULL, status TEXT NOT NULL, traffic_split REAL NOT NULL,
  winning_variant TEXT
);
CREATE TABLE sessions (
  session_id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, device TEXT NOT NULL,
  browser TEXT NOT NULL, country TEXT NOT NULL, is_returning INTEGER NOT NULL,
  referrer_id INTEGER NOT NULL REFERENCES referrers(referrer_id),
  experiment_id INTEGER REFERENCES experiments(experiment_id),
  variant TEXT, duration_seconds INTEGER NOT NULL
);
CREATE TABLE pageviews (
  pageview_id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(session_id),
  page_id INTEGER NOT NULL REFERENCES pages(page_id),
  viewed_at TEXT NOT NULL, seconds_on_page INTEGER NOT NULL,
  scroll_depth_pct INTEGER NOT NULL, exited_here INTEGER NOT NULL,
  bounce INTEGER NOT NULL, view_order INTEGER NOT NULL, device TEXT NOT NULL
);
CREATE TABLE revenue (
  revenue_id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(session_id),
  page_id INTEGER NOT NULL REFERENCES pages(page_id),
  occurred_at TEXT NOT NULL, kind TEXT NOT NULL, amount_usd REAL NOT NULL,
  currency TEXT NOT NULL, product TEXT NOT NULL, refunded INTEGER NOT NULL,
  campaign TEXT
);
"""


def main() -> None:
    rng = random.Random(6)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    db = sqlite3.connect(OUT)
    db.executescript(SCHEMA)

    sections = ["blog", "docs", "pricing", "product", "landing"]
    pages = []
    for i in range(1, 41):
        section = rng.choice(sections)
        pages.append((i, f"/{section}/page-{i}", f"{section.title()} Page {i}", section,
                      str(date(2026, 1, 1) + timedelta(days=rng.randint(0, 180))),
                      rng.choice(["ana", "bo", "cy"]), rng.randint(200, 3000),
                      1 if section == "landing" else 0,
                      {"landing": 1, "product": 2, "pricing": 3}.get(section), None))
    db.executemany("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?)", pages)

    referrers = [(i, dom, med, f"camp-{i}" if paid else None, paid,
                  "2026-01-01", round(rng.uniform(0.2, 0.95), 2), rng.choice(["NO", "US", "DE", "IN"]),
                  rng.choice([None, "gold", "silver"]), None)
                 for i, (dom, med, paid) in enumerate([
                     ("google.com", "organic", 0), ("google.com", "cpc", 1),
                     ("news.ycombinator.com", "social", 0), ("newsletter", "email", 0),
                     ("bing.com", "organic", 0), ("linkedin.com", "social", 1),
                     ("direct", "none", 0), ("partner.example", "referral", 0)], start=1)]
    db.executemany("INSERT INTO referrers VALUES (?,?,?,?,?,?,?,?,?,?)", referrers)

    experiments = [
        (1, "pricing-page-cta", "Bigger CTA lifts conversions", "2026-05-01", "2026-06-15",
         "purchase_rate", "ana", "completed", 0.5, "B"),
        (2, "landing-hero-copy", "Benefit-led copy lowers bounce", "2026-06-01", None,
         "bounce_rate", "bo", "running", 0.3, None),
    ]
    db.executemany("INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?)", experiments)

    sessions, pageviews, revenue = [], [], []
    pv_id = rev_id = 0
    for sid in range(1, 1201):
        start = date(2026, 6, 1) + timedelta(days=rng.randint(0, 60))
        exp = rng.choice([None, None, None, 1, 2])
        sessions.append((sid, f"{start}T{rng.randint(6,23):02d}:00:00",
                         rng.choice(["mobile", "desktop", "tablet"]),
                         rng.choice(["chrome", "safari", "firefox"]),
                         rng.choice(["NO", "US", "DE", "IN"]), rng.randint(0, 1),
                         rng.randint(1, 8), exp,
                         rng.choice(["A", "B"]) if exp else None, rng.randint(20, 900)))
        depth = rng.randint(1, 6)
        visited = rng.sample(range(1, 41), depth)
        for order, page in enumerate(visited, 1):
            pv_id += 1
            exited = 1 if order == depth else 0
            pageviews.append((pv_id, sid, page, f"{start}T{rng.randint(6,23):02d}:05:00",
                              rng.randint(5, 300), rng.choice([25, 50, 75, 100]),
                              exited, 1 if depth == 1 else 0, order,
                              rng.choice(["mobile", "desktop"])))
            if rng.random() < 0.06:
                rev_id += 1
                revenue.append((rev_id, sid, page, f"{start}T12:00:00",
                                rng.choice(["purchase", "subscription", "upgrade"]),
                                round(rng.uniform(5, 400), 2), "USD",
                                rng.choice(["starter", "pro", "team"]),
                                1 if rng.random() < 0.05 else 0, None))
    db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", sessions)
    db.executemany("INSERT INTO pageviews VALUES (?,?,?,?,?,?,?,?,?,?)", pageviews)
    db.executemany("INSERT INTO revenue VALUES (?,?,?,?,?,?,?,?,?,?)", revenue)
    db.commit()
    counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("pages", "referrers", "experiments", "sessions", "pageviews", "revenue")}
    print("wrote", OUT.name, counts)


if __name__ == "__main__":
    main()
