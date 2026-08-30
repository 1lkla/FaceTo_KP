#!/usr/bin/env python3
"""
Import questions from a CSV file into the EXAM-MASTER SQLite database.

CSV columns (Chinese headers, matching questions.csv):
    题号,题干,A,B,C,D,E,答案,难度,题型,类别,解析

- 题号: numeric ID, primary key (existing IDs are skipped)
- 题型: 单选题 / 多选题 / 判断题 / 填空题 / 问答题
- 问答题: option columns left empty, 答案 holds the reference answer
- 解析: optional answer explanation

Usage:
    python tools/import_csv.py <csv_path> [db_path]

Defaults: db_path comes from the DB_PATH environment variable,
falling back to database.db in the current directory.
"""

import csv
import json
import os
import sqlite3
import sys


def import_csv(csv_path, db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Ensure the analysis column exists (same migration as app.py)
    try:
        c.execute("ALTER TABLE questions ADD COLUMN analysis TEXT")
    except sqlite3.OperationalError:
        pass

    inserted, skipped = 0, 0
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            options = {}
            for opt in ['A', 'B', 'C', 'D', 'E']:
                if row.get(opt) and row[opt].strip():
                    options[opt] = row[opt]
            try:
                c.execute(
                    "INSERT INTO questions (id, stem, answer, difficulty, qtype, category, options, analysis) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        row["题号"].strip(),
                        row["题干"],
                        row["答案"],
                        row["难度"],
                        row["题型"],
                        row.get("类别", "未分类"),
                        json.dumps(options, ensure_ascii=False),
                        row.get("解析", ""),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
    conn.commit()
    conn.close()
    print(f"导入完成: 新增 {inserted} 题, 跳过已存在 {skipped} 题")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    csv_file = sys.argv[1]
    db_file = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('DB_PATH', 'database.db')
    import_csv(csv_file, db_file)
