from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .dataset import DATASET_DIR, read_csv
from .observations import phone_key


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    user_id: str
    name: str
    keys: frozenset
    emails: tuple
    matched_by: str


class IdentityIndex:
    """Current and historical identifiers per user, and which user owns each identifier."""

    def __init__(self, dataset_dir: Path = DATASET_DIR):
        self.users = {r["user_id"]: r for r in read_csv(dataset_dir / "user_identities.csv")}
        self.keys: dict[str, set] = {}
        self.emails: dict[str, list] = {}
        self.email_source: dict[str, tuple] = {}
        for uid, r in self.users.items():
            self._add(uid, "email", r["email"], "user_identities")
            self._add(uid, "phone", r["phone"], "user_identities")
            self._add(uid, "email_hash", r["email_hash"], "user_identities")
        for r in read_csv(dataset_dir / "user_audit_log.csv"):
            for value in (r["old_value"], r["new_value"]):
                self._add(r["user_id"], r["field_name"], value, r["audit_id"])
        self.owner = {k: uid for uid, ks in self.keys.items() for k in ks}

    def _add(self, uid: str, field: str, value: str, source: str) -> None:
        if not value:
            return
        keys = self.keys.setdefault(uid, {uid})
        if field == "email":
            email = value.strip().lower()
            keys |= {email, email_hash(email)}
            self.emails.setdefault(uid, [])
            if email not in self.emails[uid]:
                self.emails[uid].append(email)
            self.email_source.setdefault(email, (uid, source))
        elif field == "email_hash":
            keys.add(value.strip().lower())
        elif field == "phone":
            keys.add(phone_key(value))

    def resolve(self, email: str) -> Identity | None:
        hit = self.email_source.get(email.strip().lower())
        if hit is None:
            return None
        uid, source = hit
        return Identity(uid, self.users[uid]["name"], frozenset(self.keys[uid]), tuple(self.emails[uid]), source)

    def owners(self, keys) -> set[str]:
        return {self.owner[k] for k in keys if k in self.owner}
