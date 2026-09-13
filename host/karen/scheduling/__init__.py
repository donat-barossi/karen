from .ringing import RingController, is_dismiss_phrase
from .text_utils import alarm_spoken_label, fmt_duration, fmt_days, parse_weekdays

__all__ = [
    "ScheduleService",
    "RingController",
    "is_dismiss_phrase",
    "parse_weekdays",
    "fmt_duration",
    "fmt_days",
    "alarm_spoken_label",
]


def __getattr__(name: str):
    if name == "ScheduleService":
        from .service import ScheduleService
        return ScheduleService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
