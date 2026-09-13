#!/usr/bin/env python3
"""Test parser intent deterministici (regression suite)."""

from __future__ import annotations

import sys
from pathlib import Path

HOST = Path(__file__).resolve().parents[1] / "host"
sys.path.insert(0, str(HOST))

from karen.skills.timer_skill import parse_alarm_intent, parse_timer_intent  # noqa: E402
from karen.skills.weather_skill import parse_weather_intent  # noqa: E402


def test_alarm_list_and_next() -> None:
    assert parse_alarm_intent("quali sono le mie sveglie") == {
        "intent": "alarm",
        "parameters": {"action": "list"},
    }
    assert parse_alarm_intent("qual è la mia prossima sveglia") == {
        "intent": "alarm",
        "parameters": {"action": "next"},
    }
    assert parse_alarm_intent("salta la prossima sveglia") == {
        "intent": "alarm",
        "parameters": {"action": "skip_next"},
    }


def test_weather_city_and_when() -> None:
    assert parse_weather_intent("che tempo fa") == {
        "intent": "weather",
        "parameters": {"when": "today"},
    }
    assert parse_weather_intent("che tempo fa domani") == {
        "intent": "weather",
        "parameters": {"when": "tomorrow"},
    }
    w = parse_weather_intent("che tempo fa a milano domani")
    assert w is not None
    assert w["parameters"]["when"] == "tomorrow"
    assert w["parameters"]["city"] == "milano"


def test_timer_basic() -> None:
    t = parse_timer_intent("timer di cinque minuti")
    assert t is not None
    assert t["intent"] == "timer"
    assert t["parameters"]["duration_s"] == 300


def main() -> int:
    tests = [
        test_alarm_list_and_next,
        test_weather_city_and_when,
        test_timer_basic,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"OK  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
