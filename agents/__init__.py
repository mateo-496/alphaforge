"""Agents package for AlphaForge."""
from .risk_agent import RiskAgent, analyze_country
from .source_agent import (
    SourceAgent,
    discover_sources,
    get_country_sources,
    get_trusted_sources_for_country,
    load_trusted_registry,
    save_trusted_registry,
    add_discovered_trusted_sources,
    normalize_country_key,
)

__all__ = [
    "RiskAgent",
    "analyze_country",
    "SourceAgent",
    "discover_sources",
    "get_country_sources",
    "get_trusted_sources_for_country",
    "load_trusted_registry",
    "save_trusted_registry",
    "add_discovered_trusted_sources",
    "normalize_country_key",
]
