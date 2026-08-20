from compliance.config.settings import Settings
from compliance.db import apply_migrations, create_pool
from compliance.eval.models import EvaluationSummary


async def persist_summary(summary: EvaluationSummary, settings: Settings) -> None:
    pool = await create_pool(settings)
    try:
        await apply_migrations(pool)
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO eval_runs (
                    suite, commit_sha, faithfulness, answer_relevance,
                    context_precision, context_recall
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                summary.suite,
                summary.commit_sha,
                summary.faithfulness,
                summary.answer_relevance,
                summary.context_precision,
                summary.context_recall,
            )
    finally:
        await pool.close()
