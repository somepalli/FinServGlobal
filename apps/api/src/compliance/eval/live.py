from collections.abc import Sequence

from qdrant_client import QdrantClient

from compliance.config.settings import Settings
from compliance.eval.judge import RagasJudge
from compliance.eval.models import (
    EvaluationCase,
    EvaluationObservation,
    EvaluationResult,
)
from compliance.retrieval.answer import LocalLlmGenerator
from compliance.retrieval.embed import BgeM3Embedder
from compliance.retrieval.search import HybridSearcher


class LiveEvaluator:
    def __init__(self, settings: Settings) -> None:
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key_value)
        embedder = BgeM3Embedder(settings)
        self._searcher = HybridSearcher(client, embedder, settings)
        self._generator = LocalLlmGenerator(settings)
        self._judge = RagasJudge(settings)
        self._top_k = settings.rerank_top_k

    async def observe(self, case: EvaluationCase) -> EvaluationObservation:
        retrieved = await self._searcher.search(case.question, top_k=self._top_k)
        response = await self._generator.generate(case.question, retrieved)
        return EvaluationObservation(
            case_id=case.case_id,
            response=response,
            retrieved_clause_ids=[item.clause.clause_id for item in retrieved],
            retrieved_contexts=[item.clause.text for item in retrieved],
        )

    async def evaluate(self, cases: Sequence[EvaluationCase]) -> list[EvaluationResult]:
        results: list[EvaluationResult] = []
        for case in cases:
            observation = await self.observe(case)
            scores = await self._judge.score(case, observation)
            results.append(EvaluationResult(observation=observation, scores=scores))
        return results
