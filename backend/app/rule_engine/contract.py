from typing import Literal

from pydantic import BaseModel


class RuleResultDraft(BaseModel):
    """The shared type the real rule-checking agent (a separate repo) mirrors
    exactly. Changing this shape is a cross-repo breaking change — flag it,
    don't just edit it. See master doc §7 and CLAUDE.md's Boundaries section.
    """

    rule_id: str
    rule_version_used: int
    model_status: Literal["pass", "fail", "na", "uncertain"]
    model_finding: str
    model_pages: list[int]
    model_source_quote: str | None = None
