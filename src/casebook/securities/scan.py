"""Find real tickers and real security names in text that is about to be published."""

import json
import re
from dataclasses import dataclass
from importlib.resources import files

from casebook.securities.master import Security, load_master

# Words this product writes in upper case. No real ticker in the master may be one,
# or the scan could not tell our own text from a leak.
PRODUCT_ACRONYMS = frozenset(
    {
        "AGI", "AGR", "API", "BG", "CC", "CLI", "CPA", "CRM", "CSV", "EIN", "ETF", "FIFO",
        "FS", "HH", "HTML", "IPS", "IRA", "IRS", "JSON", "MAGI", "MCP", "NII", "NIIT", "PDF",
        "PI", "QCD", "RIA", "RMD", "RSU", "SALT", "SDK", "SEC", "SSN", "SYN", "USD", "UTC",
    }
)  # fmt: skip


@dataclass(frozen=True)
class TickerMatch:
    start: int
    end: int
    written: str
    ticker: str


class TickerFinder:
    """Real tickers in text, in any case: "MSFT", "msft", "Msft" (whole-branch review, both reviewers), everywhere.
    Encoded data is not guessed from its characters here: the one encoded field a published file holds, a provider
    signature, is left out by `published_text` before the text reaches the scan."""

    def __init__(self, master: tuple[Security, ...]) -> None:
        self._by_upper = {s.real_ticker: s.real_ticker for s in master}
        tickers = sorted(self._by_upper, key=len, reverse=True)
        self._pattern = re.compile(
            r"(?<![A-Za-z0-9])(" + "|".join(map(re.escape, tickers)) + r")(?![A-Za-z0-9])", re.IGNORECASE
        )

    def find(self, text: str) -> list[TickerMatch]:
        found: list[TickerMatch] = []
        for m in self._pattern.finditer(text):
            written = m.group(1)
            found.append(TickerMatch(m.start(1), m.end(1), written, self._by_upper[written.upper()]))
        return found


@dataclass(frozen=True)
class RealIdentifier:
    identifier: str
    kind: str


class RealIdentifierScan:
    def __init__(self, master: tuple[Security, ...], names: dict[str, list[str]], issuers: dict[str, str]):
        self._tickers = TickerFinder(master)
        phrases = sorted({n for ns in names.values() for n in ns} | set(issuers), key=len, reverse=True)
        # Any run of whitespace between a name's words still spells the name.
        flexible = (r"\s+".join(map(re.escape, phrase.split())) for phrase in phrases)
        self._names = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(flexible) + r")(?![A-Za-z0-9])", re.IGNORECASE)

    def find(self, text: str) -> list[RealIdentifier]:
        found = [RealIdentifier(m.written, "ticker") for m in self._tickers.find(text)]
        found += [RealIdentifier(m.group(1), "name") for m in self._names.finditer(text)]
        return found


def default_scan() -> RealIdentifierScan:
    raw = json.loads((files("casebook.securities") / "real_names.json").read_text(encoding="utf-8"))
    return RealIdentifierScan(load_master(), raw["names"], raw["issuers"])
