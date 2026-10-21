"""Who may read what.

Every chunk carries the access group of its document. A user's groups are looked up at query
time from the group store (in production: Keycloak or LDAP groups), so revoking a membership takes
effect on the next query without re-indexing. Everyone may read `public`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PUBLIC = "public"


class GroupStore:
    def __init__(self, users: dict[str, set[str]]):
        self._users = {u: set(g) for u, g in users.items()}

    @classmethod
    def from_json(cls, path: Path) -> "GroupStore":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls({u: set(v["groups"]) for u, v in data["users"].items()})

    def groups(self, user: str) -> set[str]:
        if user not in self._users:
            raise KeyError(f"unknown user: {user}")
        return self._users[user] | {PUBLIC}

    def grant(self, user: str, group: str) -> None:
        self._users[user].add(group)

    def revoke(self, user: str, group: str) -> None:
        self._users[user].discard(group)


def allowed_mask(chunk_groups: np.ndarray, groups: set[str]) -> np.ndarray:
    return np.isin(chunk_groups, sorted(groups))
