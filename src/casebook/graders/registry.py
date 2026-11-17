"""Which key and grader each task names, and the hash a run records for them."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

from casebook import rules, securities
from casebook.graders import (
    backdoor_roth_follow_up,
    common,
    compliance_review,
    follow_up,
    household_list,
    jury,
    meeting_follow_up,
    niit_follow_up,
    rmd_review,
    wash_sale_review,
)
from casebook.graders import concentration_basis as cb_grader
from casebook.graders import conversion_documentation as conv_grader
from casebook.graders import fee_reconciliation as fee_grader
from casebook.graders import ira_distributions as ira_grader
from casebook.keys import backdoor_roth as backdoor_keys
from casebook.keys import billing_groups as billing_keys
from casebook.keys import concentration_basis as cb_keys
from casebook.keys import conversion_documentation as conv_keys
from casebook.keys import fee_reconciliation as fee_keys
from casebook.keys import figures
from casebook.keys import ips_review as ips_keys
from casebook.keys import ira_distributions as ira_keys
from casebook.keys import issues as issue_keys
from casebook.keys import niit as niit_keys
from casebook.keys import open_follow_ups as open_follow_up_keys
from casebook.keys import positions_vs_portfolio as positions_keys
from casebook.keys import rmd as rmd_keys
from casebook.keys import rmd_sweep as rmd_sweep_keys
from casebook.keys import source_disagreements as src_keys
from casebook.keys import tax_lines as tax_lines_keys
from casebook.keys import tax_surprises as surprise_keys
from casebook.keys import wash_sale_sweep as wash_sweep_keys
from casebook.keys import wash_sales as wash_keys
from casebook.model.dates import parse_date
from casebook.model.files import household_dir

# The 2025 rules table the keys read (the RMD factors and ages, the wash-sale window).
RULES_2025 = Path(rules.__file__ or "").with_name("rules_2025.toml")
# The security master, which the IPS keys read to tell a single company's stock from a fund.
SECURITY_MASTER = Path(securities.__file__ or "").with_name("master.json")


class UnknownGraderError(KeyError):
    pass


@dataclass(frozen=True)
class GraderSpec:
    name: str
    # The key from the book, the task's household (or "book" for a book-level task) and its grader_params.
    key: Callable[[Path, str, dict[str, Any]], Any]
    # (output, key, fixtures) -> Grade; a follow-up task's grader also takes the run's FollowUp.
    grade: Callable[..., Any]
    sources: tuple[Path, ...]
    # Whether the task records its follow-up in the CRM sandbox and drafts a client message for the tone jury.
    follow_up: bool = False

    def sha256(self) -> str:
        digest = hashlib.sha256()
        for path in self.sources:
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        return digest.hexdigest()


def _date(params: dict[str, Any], name: str) -> date:
    value = params[name]
    return value if isinstance(value, date) else parse_date(str(value))


def _sources(*modules: ModuleType) -> tuple[Path, ...]:
    """The files a grader's hash covers: its key's and grader's own, the shared base every key and grader
    stands on, and the 2025 rules table the keys read, so a change to any of them changes the hash."""
    return (*(Path(m.__file__ or "") for m in (*modules, common, figures)), RULES_2025)


def _follow_up_sources(*modules: ModuleType) -> tuple[Path, ...]:
    """A follow-up grader's: also the shared follow-up rules and the tone jury, whose rubric is part of it."""
    return _sources(*modules, meeting_follow_up, follow_up, jury)


GRADERS = {
    "fee_reconciliation": GraderSpec(
        name="fee_reconciliation",
        key=lambda book, household, params: fee_keys.fee_key(
            book / household_dir(household), _date(params, "quarter_end")
        ),
        grade=fee_grader.grade,
        sources=_sources(fee_keys, fee_grader),
    ),
    "billing_groups": GraderSpec(
        name="billing_groups",
        key=lambda book, household, params: billing_keys.billing_groups_key(book, _date(params, "as_of")),
        grade=household_list.grade,
        sources=_sources(billing_keys, fee_keys, household_list),
    ),
    "positions_vs_portfolio": GraderSpec(
        name="positions_vs_portfolio",
        key=lambda book, household, params: positions_keys.positions_key(book, _date(params, "as_of")),
        grade=household_list.grade,
        sources=_sources(positions_keys, fee_keys, household_list),
    ),
    "wash_sale_review": GraderSpec(
        name="wash_sale_review",
        key=lambda book, household, params: wash_keys.wash_sale_key(book / household_dir(household)),
        grade=wash_sale_review.grade,
        sources=_sources(wash_keys, wash_sale_review),
    ),
    "ira_distributions": GraderSpec(
        name="ira_distributions",
        key=lambda book, household, params: ira_keys.ira_distributions_key(book / household_dir(household)),
        grade=ira_grader.grade,
        sources=_sources(ira_keys, rmd_keys, ira_grader),
    ),
    "rmd_review": GraderSpec(
        name="rmd_review",
        key=lambda book, household, params: rmd_keys.household_rmd(book / household_dir(household)),
        grade=rmd_review.grade,
        sources=_sources(rmd_keys, rmd_review),
    ),
    "rmd_sweep": GraderSpec(
        name="rmd_sweep",
        key=lambda book, household, params: rmd_sweep_keys.rmd_sweep_key(book),
        grade=household_list.grade,
        sources=_sources(rmd_sweep_keys, rmd_keys, household_list),
    ),
    "wash_sale_sweep": GraderSpec(
        name="wash_sale_sweep",
        key=lambda book, household, params: wash_sweep_keys.wash_sale_sweep_key(book),
        grade=household_list.grade,
        sources=_sources(wash_sweep_keys, wash_keys, household_list),
    ),
    "concentration_basis": GraderSpec(
        name="concentration_basis",
        key=lambda book, household, params: cb_keys.concentration_basis_key(
            book / household_dir(household), _date(params, "as_of"), int(params["tax_year"])
        ),
        grade=cb_grader.grade,
        sources=(*_sources(cb_keys, ips_keys, issue_keys, cb_grader, compliance_review), SECURITY_MASTER),
    ),
    "conversion_documentation": GraderSpec(
        name="conversion_documentation",
        key=lambda book, household, params: conv_keys.conversion_key(
            book / household_dir(household), int(params["year"])
        ),
        grade=conv_grader.grade,
        sources=_sources(conv_keys, issue_keys, conv_grader, compliance_review),
    ),
    "ips_sweep": GraderSpec(
        name="ips_sweep",
        key=lambda book, household, params: ips_keys.ips_sweep_key(book, _date(params, "as_of")),
        grade=compliance_review.grade_household_list,
        sources=(*_sources(ips_keys, compliance_review, household_list), SECURITY_MASTER),
    ),
    "source_disagreements": GraderSpec(
        name="source_disagreements",
        key=lambda book, household, params: src_keys.source_disagreements_key(book),
        grade=compliance_review.grade_household_list,
        sources=_sources(src_keys, compliance_review, household_list),
    ),
    "backdoor_roth_follow_up": GraderSpec(
        name="backdoor_roth_follow_up",
        key=lambda book, household, params: backdoor_keys.backdoor_roth_key(book / household_dir(household)),
        grade=backdoor_roth_follow_up.grade,
        sources=_follow_up_sources(backdoor_keys, tax_lines_keys, backdoor_roth_follow_up),
        follow_up=True,
    ),
    "niit_follow_up": GraderSpec(
        name="niit_follow_up",
        key=lambda book, household, params: niit_keys.niit_key(book / household_dir(household)),
        grade=niit_follow_up.grade,
        sources=_follow_up_sources(niit_keys, niit_follow_up),
        follow_up=True,
    ),
    "open_follow_ups": GraderSpec(
        name="open_follow_ups",
        key=lambda book, household, params: open_follow_up_keys.open_follow_ups_key(book, _date(params, "as_of")),
        grade=household_list.grade,
        sources=_sources(open_follow_up_keys, household_list),
    ),
    "tax_surprises": GraderSpec(
        name="tax_surprises",
        key=lambda book, household, params: surprise_keys.tax_surprises_key(book),
        grade=household_list.grade,
        sources=_sources(
            surprise_keys,
            backdoor_keys,
            tax_lines_keys,
            rmd_sweep_keys,
            rmd_keys,
            wash_sweep_keys,
            wash_keys,
            household_list,
        ),
    ),
}


def grader(name: str) -> GraderSpec:
    if name not in GRADERS:
        raise UnknownGraderError(f"no grader named {name!r}")
    return GRADERS[name]
