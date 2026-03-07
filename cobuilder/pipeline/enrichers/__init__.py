"""LLM enrichment pipeline for CoBuilder node graph processing.

This package implements a sequential enrichment pipeline where each enricher
makes LLM calls to append structured data to pipeline nodes.

Usage:
    from cobuilder.pipeline.enrichers import EnrichmentPipeline

    pipeline = EnrichmentPipeline()
    enriched_nodes = pipeline.enrich(nodes, repomap, sd)
"""
import os
from .base import BaseEnricher
from .file_scoper import FileScoper
from .acceptance_crafter import AcceptanceCrafter
from .dependency_inferrer import DependencyInferrer
from .worker_selector import WorkerSelector
from .complexity_sizer import ComplexitySizer

__all__ = [
    "EnrichmentPipeline",
    "BaseEnricher",
    "FileScoper",
    "AcceptanceCrafter",
    "DependencyInferrer",
    "WorkerSelector",
    "ComplexitySizer",
]


class EnrichmentPipeline:
    """Chains all enrichers sequentially to fully annotate pipeline nodes.

    Each enricher receives the node list as enriched by the previous enricher,
    so later enrichers can build on keys set by earlier ones (e.g., WorkerSelector
    uses file_scope set by FileScoper).
    """

    enrichers = [
        FileScoper,
        AcceptanceCrafter,
        DependencyInferrer,
        WorkerSelector,
        ComplexitySizer,
    ]

    def enrich(self, nodes: list[dict], repomap: dict, sd: str) -> list[dict]:
        """Run all enrichers sequentially over the node list.

        Args:
            nodes: List of node dicts from the pipeline graph.
            repomap: Repository map dict (module → metadata/dependencies).
            sd: Solution design document text.

        Returns:
            Enriched node list with all enricher keys appended.
        """
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        for enricher_cls in self.enrichers:
            enricher = enricher_cls(model=model)
            nodes = enricher.enrich_all(nodes, repomap, sd)
        return nodes
