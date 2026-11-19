import asyncio
import logging

from . import db
from .agent import run_agent

log = logging.getLogger(__name__)


async def worker():
    """Execute one persisted task at a time; queued tasks survive process restarts."""
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
                db.finish_task(task_id, "succeeded", answer)
                db.reconcile_objective_task(task_id, "succeeded", result=answer)
            except asyncio.CancelledError:
                # The task remains recoverable after restart.
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
