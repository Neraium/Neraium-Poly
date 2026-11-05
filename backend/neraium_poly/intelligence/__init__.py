"""Causal, evidence-qualified market relationship analysis (research only)."""

from .engine import (
    EvidenceContext,
    RelationshipEngine,
    RelationshipGraph,
    RelationshipPolicy,
    discover_statistical_relationship,
)

__all__ = [
    "EvidenceContext",
    "RelationshipEngine",
    "RelationshipGraph",
    "RelationshipPolicy",
    "discover_statistical_relationship",
]
