import asyncio
import logging

from . import db
from .agent import run_agent
from . import objective_verification

log = logging.getLogger(__name__)


async def worker():
    """Execute persisted tasks; objective steps succeed only after deterministic checks pass."""
    while True:
        try:
            task = db.claim_task()
            if task is None:
                await asyncio.sleep(1)
                continue

            task_id = task["id"]
            db.reconcile_objective_task(task_id, "running")
            try:
                result = await run_agent(task["prompt"])
                answer = result.get("answer", "Tâche terminée.")
                evidence = objective_verification.verify_task(task_id, result)
                if evidence is None or evidence.get("success"):
                    db.finish_task(task_id, "succeeded", answer)
                    db.reconcile_objective_task(task_id, "succeeded", result=answer)
                else:
                    error = objective_verification.format_failure(evidence)
                    db.finish_task(task_id, "failed", result=answer, error=error)
                    db.reconcile_objective_task(task_id, "failed", result=answer, error=error)
            except asyncio.CancelledError:
                db.finish_task(task_id, "queued", error="Worker arrêté ; tâche remise en attente.")
                db.reconcile_objective_task(task_id, "queued", error="Worker arrêté ; tâche remise en attente.")
                raise
            except Exception as exc:
                log.exception("Task %s failed", task_id)
                db.finish_task(task_id, "failed", error=str(exc))
                db.reconcile_objective_task(task_id, "failed", error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Task queue worker error")
            await asyncio.sleep(2)
