"""Servizio sveglie e timer multipli."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..ha_client import HomeAssistantClient
from ..scheduling.ringing import RingController
from .store import ScheduleStore

log = logging.getLogger(__name__)

WEEKDAY_IT = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")

DAY_ALIASES: dict[str, int] = {
    "lun": 0, "lunedì": 0, "lunedi": 0,
    "mar": 1, "martedì": 1, "martedi": 1,
    "mer": 2, "mercoledì": 2, "mercoledi": 2,
    "gio": 3, "giovedì": 3, "giovedi": 3,
    "ven": 4, "venerdì": 4, "venerdi": 4,
    "sab": 5, "sabato": 5,
    "dom": 6, "domenica": 6,
}


def parse_weekdays(text: str) -> list[int] | None:
    t = text.lower()
    found: set[int] = set()
    for key, wd in DAY_ALIASES.items():
        if key in t:
            found.add(wd)
    if "feriali" in t:
        found.update({0, 1, 2, 3, 4})
    if "weekend" in t or "fine settimana" in t:
        found.update({5, 6})
    if "tutti i giorni" in t or "ogni giorno" in t:
        return list(range(7))
    return sorted(found) if found else None


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} secondi"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        out = f"{m} minut{'o' if m == 1 else 'i'}"
        return out + (f" e {s} secondi" if s else "")
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    out = f"{h} or{'a' if h == 1 else 'e'}"
    return out + (f" e {m} minuti" if m else "")


def fmt_days(days: list[int]) -> str:
    return ", ".join(WEEKDAY_IT[d] for d in sorted(days))


class ScheduleService:
    def __init__(self, cfg: dict) -> None:
        host_dir = Path(__file__).resolve().parent.parent.parent
        sched_cfg = cfg.get("schedule", {})
        store_path = host_dir / sched_cfg.get("data_dir", "data") / "schedules.json"
        self._store = ScheduleStore(store_path)
        self._tz = ZoneInfo(cfg.get("ha", {}).get("timezone", "Europe/Rome"))
        self._ha_cfg = cfg.get("ha", {})
        self._voice_announce: Any = None
        self._ring_controller: RingController | None = None
        self._task: asyncio.Task | None = None
        self._data = self._store.load()

    def set_voice_announce(self, callback: Any) -> None:
        """Callback async(message: str) → annuncio TTS su ESP32."""
        self._voice_announce = callback

    def set_ring_controller(self, ring: RingController) -> None:
        self._ring_controller = ring

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
            log.info("Scheduler sveglie/timer avviato (%d sveglie, %d timer)",
                     len(self._data["alarms"]), len(self._data["timers"]))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _persist(self) -> None:
        self._store.save(self._data)

    def start_timer(self, duration_s: int, name: str = "") -> dict[str, Any]:
        now = datetime.now(self._tz)
        ends = now + timedelta(seconds=duration_s)
        timer = {
            "id": uuid.uuid4().hex[:8],
            "name": name.strip() or f"timer-{len(self._data['timers']) + 1}",
            "ends_at": ends.isoformat(),
            "duration_s": duration_s,
            "fired": False,
        }
        self._data["timers"].append(timer)
        self._persist()
        log.info(
            "Timer '%s' avviato (%s), scade alle %s",
            timer["name"],
            fmt_duration(duration_s),
            ends.strftime("%H:%M:%S"),
        )
        return timer

    def list_timers(self) -> list[dict[str, Any]]:
        now = datetime.now(self._tz)
        active: list[dict[str, Any]] = []
        for t in self._data["timers"]:
            if t.get("fired"):
                continue
            try:
                ends = datetime.fromisoformat(t["ends_at"])
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=self._tz)
            except ValueError:
                continue
            if ends > now:
                active.append({**t, "remaining_s": int((ends - now).total_seconds())})
        return active

    def cancel_timers(self, *, name: str = "", timer_id: str = "", cancel_all: bool = False) -> int:
        if cancel_all:
            n = sum(1 for t in self._data["timers"] if not t.get("fired"))
            self._data["timers"] = [t for t in self._data["timers"] if t.get("fired")]
            self._persist()
            return n

        if not name and not timer_id:
            for i in range(len(self._data["timers"]) - 1, -1, -1):
                if not self._data["timers"][i].get("fired"):
                    del self._data["timers"][i]
                    self._persist()
                    return 1
            return 0

        name_l = name.lower().strip()
        keep: list[dict[str, Any]] = []
        removed = 0
        for t in self._data["timers"]:
            if t.get("fired"):
                keep.append(t)
                continue
            match = (timer_id and t.get("id") == timer_id) or (
                name_l and name_l in t.get("name", "").lower()
            )
            if match:
                removed += 1
            else:
                keep.append(t)
        self._data["timers"] = keep
        self._persist()
        return removed

    def describe_timers(self) -> str:
        active = self.list_timers()
        if not active:
            return "Non ci sono timer attivi."
        parts = [f"{t['name']}: {fmt_duration(int(t['remaining_s']))}" for t in active]
        return "Timer attivi: " + "; ".join(parts) + "."

    def upsert_alarm(
        self,
        hour: int,
        minute: int,
        days: list[int],
        *,
        name: str = "",
        alarm_id: str = "",
    ) -> dict[str, Any]:
        if alarm_id:
            for alarm in self._data["alarms"]:
                if alarm.get("id") == alarm_id:
                    alarm.update({"hour": hour, "minute": minute, "days": days, "enabled": True})
                    if name:
                        alarm["name"] = name
                    self._persist()
                    return alarm

        alarm = {
            "id": uuid.uuid4().hex[:8],
            "name": name or f"sveglia-{len(self._data['alarms']) + 1}",
            "hour": hour,
            "minute": minute,
            "days": sorted(set(days)),
            "enabled": True,
            "skip_dates": [],
            "last_fired": "",
        }
        self._data["alarms"].append(alarm)
        self._persist()
        return alarm

    def list_alarms(self) -> list[dict[str, Any]]:
        return [a for a in self._data["alarms"] if a.get("enabled", True)]

    def skip_tomorrow(self, alarm_id: str = "") -> int:
        tomorrow = date.today() + timedelta(days=1)
        iso = tomorrow.isoformat()
        count = 0
        for alarm in self._data["alarms"]:
            if not alarm.get("enabled", True):
                continue
            if alarm_id and alarm.get("id") != alarm_id:
                continue
            if tomorrow.weekday() not in alarm.get("days", []):
                continue
            skips = alarm.setdefault("skip_dates", [])
            if iso not in skips:
                skips.append(iso)
                count += 1
        self._persist()
        return count

    def skip_next(self, alarm_id: str = "") -> int:
        now = datetime.now(self._tz)
        count = 0
        for alarm in self._data["alarms"]:
            if not alarm.get("enabled", True):
                continue
            if alarm_id and alarm.get("id") != alarm_id:
                continue
            nxt = self._next_occurrence(alarm, after=now)
            if nxt is None:
                continue
            iso = nxt.date().isoformat()
            skips = alarm.setdefault("skip_dates", [])
            if iso not in skips:
                skips.append(iso)
                count += 1
        self._persist()
        return count

    def disable_alarm(self, alarm_id: str = "", name: str = "") -> bool:
        name_l = name.lower()
        for alarm in self._data["alarms"]:
            if alarm_id and alarm.get("id") != alarm_id:
                continue
            if name_l and name_l not in alarm.get("name", "").lower():
                continue
            alarm["enabled"] = False
            self._persist()
            return True
        return False

    def describe_alarms(self) -> str:
        alarms = self.list_alarms()
        if not alarms:
            return "Non hai sveglie attive."
        parts = [
            f"{a.get('name', 'sveglia')}: {int(a['hour']):02d}:{int(a['minute']):02d} "
            f"({fmt_days(a.get('days', []))})"
            for a in alarms
        ]
        return "Sveglie: " + "; ".join(parts) + "."

    def _next_occurrence(self, alarm: dict[str, Any], after: datetime) -> datetime | None:
        days = alarm.get("days", [])
        if not days:
            return None
        skips = set(alarm.get("skip_dates", []))
        hour, minute = int(alarm["hour"]), int(alarm["minute"])
        for offset in range(1, 8):
            day = after.date() + timedelta(days=offset)
            if day.weekday() not in days:
                continue
            if day.isoformat() in skips:
                continue
            return datetime.combine(day, datetime.min.time(), tzinfo=self._tz).replace(
                hour=hour, minute=minute
            )
        return None

    async def _start_ring(self, message: str, kind: str) -> None:
        if self._ring_controller:
            await self._ring_controller.start(message, kind=kind)
            return
        await self._announce(message)

    async def _announce(self, message: str) -> None:
        if self._voice_announce:
            try:
                await self._voice_announce(message)
                log.info("Annuncio vocale ESP: %s", message)
            except Exception:
                log.exception("Annuncio vocale ESP fallito")

        ha = HomeAssistantClient(self._ha_cfg)
        script = self._ha_cfg.get("entities", {}).get("announce_script", "script.karen_announce")
        ok = await ha.call_service(
            "script.turn_on",
            entity_id=script,
            message=message,
        )
        if not ok:
            await ha.call_service("persistent_notification.create", title="Karen", message=message)
        log.info("Annuncio HA: %s", message)

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                log.exception("Errore scheduler")
            await asyncio.sleep(5)

    async def _tick(self) -> None:
        now = datetime.now(self._tz)
        today = now.date().isoformat()
        now_hm = (now.hour, now.minute)

        changed = False
        for alarm in self._data["alarms"]:
            skips = alarm.get("skip_dates", [])
            if skips:
                fresh = [d for d in skips if d >= today]
                if len(fresh) != len(skips):
                    alarm["skip_dates"] = fresh
                    changed = True

        for timer in self._data["timers"]:
            if timer.get("fired"):
                continue
            try:
                ends = datetime.fromisoformat(timer["ends_at"])
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=self._tz)
            except ValueError:
                continue
            if ends <= now:
                timer["fired"] = True
                changed = True
                await self._start_ring("Tempo scaduto!", kind="timer")

        if changed:
            self._data["timers"] = [t for t in self._data["timers"] if not t.get("fired")]
            self._persist()

        for alarm in self._data["alarms"]:
            if not alarm.get("enabled", True):
                continue
            if now.weekday() not in alarm.get("days", []):
                continue
            if today in alarm.get("skip_dates", []):
                continue
            if (int(alarm["hour"]), int(alarm["minute"])) != now_hm:
                continue
            if alarm.get("last_fired") == today:
                continue
            alarm["last_fired"] = today
            self._persist()
            await self._start_ring(
                f"{alarm.get('name', 'Sveglia')}! È ora di svegliarsi.",
                kind="alarm",
            )
