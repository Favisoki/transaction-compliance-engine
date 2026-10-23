"""Compliance engine package.

Importing :mod:`app.services.compliance.rules` is what populates the registry,
so it must happen before :func:`build_compliance_engine` is called.
"""

from app.services.compliance import rules as _rules  # noqa: F401  (registration side effect)
from app.services.compliance.base import (
    ComplianceRule,
    clear_registry_for_tests,
    register_rule,
    registered_rules,
)
from app.services.compliance.engine import ComplianceEngine, build_compliance_engine
from app.services.compliance.types import (
    ComplianceDecision,
    RuleContext,
    RuleViolation,
)

__all__ = [
    "ComplianceDecision",
    "ComplianceEngine",
    "ComplianceRule",
    "RuleContext",
    "RuleViolation",
    "build_compliance_engine",
    "clear_registry_for_tests",
    "register_rule",
    "registered_rules",
]
