from typing import Literal

from pydantic import BaseModel


class RuleResultDraft(BaseModel):
    """The shared type the real rule-checking agent (a separate repo) mirrors
    exactly. Changing this shape is a cross-repo breaking change — flag it,
    don't just edit it. See master doc §7 and CLAUDE.md's Boundaries section.

    2026-07-30: added "not_checkable" — agent-making's real result
    vocabulary distinguishes "the rule doesn't apply here" (na) from "we
    couldn't determine an answer" (not_checkable — payor detection failing
    for a payor-specific rule, a deterministic checker not finding the text
    pattern it needed in this specific document, or a rule with no checker
    implemented at all; see agent-making/agent/pipeline/fields.py's own
    module docstring and DET_CHECKS fallback) and this contract now keeps
    that distinction instead of collapsing it into "na". Requires the
    matching Postgres enum value (migration ff6ae00976bd) and
    RuleResultOut's Literal (app/routers/rule_results.py) to both already
    exist before this is used.
    """

    rule_id: str
    rule_version_used: int
    model_status: Literal["pass", "fail", "na", "uncertain", "not_checkable"]
    model_finding: str
    model_pages: list[int]
    model_source_quote: str | None = None
