from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    token: str
    db_path: str

    @classmethod
    def from_env(cls) -> Config:
        db_path = os.environ.get("DB_PATH", "firooz.db")
        return cls(token="", db_path=db_path)
