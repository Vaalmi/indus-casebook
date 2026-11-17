"""What every compliance key shares: an issue a reviewer should look at, and the records an answer must name
for it (by their IDs: accounts, securities, lots, transactions, CRM records, documents)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    name: str
    records: tuple[str, ...]
