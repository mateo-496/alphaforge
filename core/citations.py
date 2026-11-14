"""Code-enforced sourcing: the report writer may only cite claim ids.

`resolve_citations` turns [claim:id] into numbered references and raises if any
sentence has no valid claim id, so sourcing never depends on the LLM.
"""
import re

from core.schemas import AgentOutput, Claim

CITE_RE = re.compile(r"\[([a-z_]+:[A-Za-z0-9.\-]+:\d+)\]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class CitationError(ValueError):
    pass


def claim_index(outputs: list[AgentOutput]) -> dict[str, Claim]:
    index: dict[str, Claim] = {}
    for out in outputs:
        for c in out.claims:
            if c.id in index:
                raise CitationError(f"Duplicate claim id {c.id}")
            index[c.id] = c
    return index


def resolve_citations(text: str, outputs: list[AgentOutput]) -> tuple[str, list[Claim]]:
    """Return (text with [n] markers, cited claims in order). Fails on uncited/unknown ids."""
    index = claim_index(outputs)
    order: list[str] = []
    problems: list[str] = []
    for sentence in filter(None, (s.strip() for s in SENTENCE_RE.split(text))):
        ids = CITE_RE.findall(sentence)
        if not ids:
            problems.append(f"no claim id: {sentence[:80]!r}")
        for i in ids:
            if i not in index:
                problems.append(f"unknown claim id {i}")
            elif i not in order:
                order.append(i)
    if problems:
        raise CitationError("; ".join(problems))
    numbers = {cid: n for n, cid in enumerate(order, 1)}
    resolved = CITE_RE.sub(lambda m: f"[{numbers[m.group(1)]}]", text)
    return resolved, [index[cid] for cid in order]


def format_references(cited: list[Claim]) -> str:
    lines = []
    for n, c in enumerate(cited, 1):
        for s in c.sources:
            lines.append(f"[{n}] {s.title}, {s.locator}. {s.url} (retrieved {s.retrieved_at})")
    return "\n".join(lines)
