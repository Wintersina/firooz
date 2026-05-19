"""Import Persian poems from the ChronologicalPersianPoetryDataset TSV."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firooz.models import Base, Poem  # noqa: E402

csv.field_size_limit(1_000_000)

TARGET_POETS = {"حافظ", "مولوی", "سعدی"}

DEFAULT_TSV = "/tmp/poems.tsv"
DEFAULT_DB = "firooz.db"


def main(tsv_path: str = DEFAULT_TSV, db_path: str = DEFAULT_DB) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        existing = session.execute(select(Poem.id).limit(1)).scalar_one_or_none()
        if existing is not None:
            print(f"Poems table already has data. Delete rows first to re-import.")
            return

    count = 0
    batch: list[Poem] = []
    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            poet = row["poet"].strip()
            if poet not in TARGET_POETS:
                continue
            # Replace 4-space verse separator with newline
            text = row["poem"].replace("    ", "\n")
            batch.append(Poem(
                poet=poet,
                book_title=row.get("book_title", "").strip(),
                poem_title=row.get("poem_title", "").strip(),
                text=text,
            ))
            count += 1

            if len(batch) >= 500:
                with Session(engine) as session:
                    session.add_all(batch)
                    session.commit()
                batch = []

    if batch:
        with Session(engine) as session:
            session.add_all(batch)
            session.commit()

    print(f"Imported {count} poems from {TARGET_POETS}")


if __name__ == "__main__":
    tsv = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TSV
    db = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB
    main(tsv, db)
