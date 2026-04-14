#!/usr/bin/env python3
"""Interactive setup script to store the Discord bot token in the database."""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DB_PATH_DEFAULT = "firooz.db"


class Base(DeclarativeBase):
    pass


class Config(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


def configure(db_path: str, token: str | None = None) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    if token is None:
        print("=" * 50)
        print("  Firooz - Configuration")
        print("=" * 50)
        print()
        print("You need a Discord bot token. Here's how to get one:")
        print()
        print("1. Go to https://discord.com/developers/applications")
        print("2. Click 'New Application' and give it a name")
        print("3. Go to 'Bot' in the left sidebar")
        print("4. Enable 'Message Content Intent' under Privileged Intents")
        print("5. Click 'Reset Token' and copy it")
        print()
        print("Then invite the bot to your server:")
        print("6. Go to 'OAuth2' in the left sidebar")
        print("7. Check 'bot' under Scopes")
        print("8. Check 'Send Messages', 'Read Message History', 'View Channels'")
        print("9. Open the generated URL to invite the bot")
        print()
        token = input("Paste your bot token here: ").strip()

    if not token:
        print("ERROR: Token cannot be empty.")
        sys.exit(1)

    with Session(engine) as session:
        existing = session.execute(
            select(Config).where(Config.key == "discord_bot_token")
        ).scalar_one_or_none()

        if existing:
            existing.value = token
        else:
            session.add(Config(key="discord_bot_token", value=token))

        session.commit()

    print()
    print(f"Token saved to {db_path}")
    print("Run 'make run' to start the bot!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the Firooz")
    parser.add_argument(
        "--db",
        default=os.environ.get("DB_PATH", DB_PATH_DEFAULT),
        help="Path to the SQLite database",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bot token (will prompt interactively if not provided)",
    )
    args = parser.parse_args()
    configure(db_path=args.db, token=args.token)


if __name__ == "__main__":
    main()
