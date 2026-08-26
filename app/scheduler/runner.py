import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.domain.scheduling import QuietHoursPolicy
from app.services.scheduler import SchedulerDecision, claim_due_modes

logger = logging.getLogger(__name__)


class PersistentScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float,
        batch_size: int,
        default_quiet_hours: QuietHoursPolicy | None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("'poll_interval_seconds' must be positive.")
        if batch_size <= 0:
            raise ValueError("'batch_size' must be positive.")

        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._default_quiet_hours = default_quiet_hours
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def run_once(self, *, now: datetime | None = None) -> list[SchedulerDecision]:
        current_time = now or datetime.now(UTC)
        with self._session_factory.begin() as session:
            return claim_due_modes(
                session,
                now=current_time,
                default_quiet_hours=self._default_quiet_hours,
                batch_size=self._batch_size,
            )

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="homeagent-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                decisions = await asyncio.to_thread(self.run_once)
                for decision in decisions:
                    logger.info(
                        "scheduler_decision action=%s mode=%s run_id=%s next_run_at=%s message=%s",
                        decision.action.value,
                        decision.instance_key,
                        decision.run_id,
                        decision.next_run_at,
                        decision.message,
                    )
            except Exception:
                logger.exception("scheduler_tick_failed")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue
