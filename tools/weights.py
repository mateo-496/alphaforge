"""Country weight construction for one asset. Pure code, no LLM."""

OTHER = "Other"


def split_region(share: float, proportions: dict[str, float]) -> dict[str, float]:
    """Split a regional share (e.g. EMEA) across countries by proportions (GDP or known footprint).
    The result is an ESTIMATE: callers must flag the claim / set weights_estimated."""
    total = sum(proportions.values())
    return {c: share * p / total for c, p in proportions.items()} if total > 0 else {}


def blend(rev: dict[str, float], prod: dict[str, float] | None, a: float = 0.7) -> dict[str, float]:
    """w_ic = a * w_rev + (1-a) * w_prod. Without production data, revenue weights are used as is."""
    if not prod:
        return dict(rev)
    return {c: a * rev.get(c, 0.0) + (1 - a) * prod.get(c, 0.0) for c in set(rev) | set(prod)}


def select_countries(w: dict[str, float], coverage: float = 0.85, floor: float = 0.05,
                     global_name: str = OTHER) -> dict[str, float]:
    """Keep countries by decreasing weight until `coverage` is reached, drop any below `floor`;
    the remainder goes to 'Other' (scored with the global GPR). Output sums to the input total."""
    total = sum(w.values())
    kept: dict[str, float] = {}
    covered = 0.0
    for c, x in sorted(((c, x) for c, x in w.items() if c != global_name), key=lambda t: -t[1]):
        if covered >= coverage * total or x < floor:
            break
        kept[c] = x
        covered += x
    kept[global_name] = total - covered
    return kept
