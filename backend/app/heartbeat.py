import asyncio
import logging
from . import db
from .agent import run_agent

log = logging.getLogger(__name__)

async def worker():
    while True:
        try:
            config = db.get_heartbeat()
            if config["enabled"]:
                db.record_heartbeat("running", "Cycle heartbeat démarré.")
                try:
                    result = await run_agent(
                        "[HEARTBEAT] " + config["prompt"] +
                        "\nObserve uniquement les tâches et fichiers autorisés. "
                        "Ne supprime rien, ne modifie pas la configuration et rapporte les actions."
                    )
                    db.record_heartbeat("success", result.get("answer", "Cycle terminé."))
                except Exception as exc:
                    log.exception("Heartbeat failed")
                    db.record_heartbeat("error", error=str(exc))
                await asyncio.sleep(max(30, min(config["interval_seconds"], 86400)))
            else:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Heartbeat scheduler error")
            await asyncio.sleep(10)
