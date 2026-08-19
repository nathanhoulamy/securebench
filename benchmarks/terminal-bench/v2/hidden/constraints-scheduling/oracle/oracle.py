"""Host-only Oracle for the constraints-scheduling conversion."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


EMAILS = {"alice@example.com", "bob@example.com", "carol@example.com"}
TIMESTAMP = re.compile(r"^\d{8}T\d{6}Z$")


class ScheduleOracle:
    def __init__(self) -> None:
        self.calendars: tuple[str, ...] = ()
        self.errors: list[str] = []
        self.evaluated = False

    def initialize(self, request: dict[str, Any]) -> None:
        resources = request.get("resources")
        if not isinstance(resources, dict):
            raise ValueError("resources are required")
        by_mount: dict[str, str] = {}
        for resource in resources.values():
            if not isinstance(resource, dict):
                continue
            mount = resource.get("mount")
            source = resource.get("source_path")
            if isinstance(mount, str) and isinstance(source, str):
                by_mount[mount] = source
        paths = [
            by_mount.get("/app/alice_calendar.ics"),
            by_mount.get("/app/bob_calendar.ics"),
            by_mount.get("/app/carol_calendar.ics"),
        ]
        if not all(isinstance(path, str) for path in paths):
            raise ValueError("public calendar resources are unavailable")
        self.calendars = tuple(Path(path).read_text() for path in paths)

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = error.get("code") if isinstance(error, dict) else "artifact_rejected"
            self.errors.append(str(code))
            return
        parsed = evidence.get("parsed_value")
        if not isinstance(parsed, dict):
            self.errors.append("invalid_calendar")
            return
        self.errors.extend(self._validate_calendar(parsed))

    def _validate_calendar(self, calendar: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        calendar_properties = _properties(calendar.get("properties"))
        if "2.0" not in calendar_properties.get("VERSION", []):
            errors.append("missing_version")
        if not calendar_properties.get("PRODID"):
            errors.append("missing_prodid")

        events = calendar.get("events")
        if not isinstance(events, list):
            return [*errors, "missing_event"]
        matching: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            properties = _properties(event.get("properties"))
            attendees = {
                value.lower().removeprefix("mailto:")
                for value in properties.get("ATTENDEE", [])
            }
            if "Team Planning Meeting" in properties.get("SUMMARY", []) and EMAILS <= attendees:
                matching.append(properties)
        if len(matching) != 1:
            return [*errors, "meeting_event_not_unique"]
        meeting = matching[0]
        start = _one_timestamp(meeting, "DTSTART", errors)
        end = _one_timestamp(meeting, "DTEND", errors)
        if start is None or end is None:
            return errors
        if end - start != timedelta(hours=1):
            errors.append("duration_not_one_hour")
        if not (
            start.year == 2024
            and start.month == 1
            and 15 <= start.day <= 19
            and start.weekday() < 5
        ):
            errors.append("outside_date_window")
        if not _hard_ok(start, end):
            errors.append("hard_constraint_violation")
        if any(_overlap(start, end, calendar_text) for calendar_text in self.calendars):
            errors.append("calendar_conflict")
        if errors:
            return errors

        earlier = _earliest_valid(self.calendars)
        if earlier is None or start != earlier:
            errors.append("not_earliest_valid_slot")
        if not 9 <= start.hour < 12:
            errors.append("morning_preference_not_satisfied")
        _check_carol_buffer(start, end, self.calendars[2], errors)
        return errors

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and not self.errors
        if passed:
            message = "Schedule satisfies the declared constraints"
        elif not self.evaluated:
            message = "Schedule artifact was not evaluated"
        else:
            message = "Schedule did not satisfy all declared constraints"
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"schedule_artifact": passed},
                "public_diagnostics": {
                    "message": message,
                    "failure_categories": sorted(set(self.errors)),
                },
            },
        }


def _properties(value: Any) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    if not isinstance(value, list):
        return output
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        property_value = item.get("value")
        if isinstance(name, str) and isinstance(property_value, str):
            output.setdefault(name.upper(), []).append(property_value)
    return output


def _one_timestamp(
    properties: dict[str, list[str]],
    name: str,
    errors: list[str],
) -> datetime | None:
    values = properties.get(name, [])
    if len(values) != 1 or not TIMESTAMP.fullmatch(values[0]):
        errors.append(f"invalid_{name.lower()}")
        return None
    return datetime.strptime(values[0], "%Y%m%dT%H%M%SZ")


def _calendar_intervals(calendar: str) -> tuple[tuple[datetime, datetime], ...]:
    starts = re.findall(r"^DTSTART:(\d{8}T\d{6}Z)$", calendar, flags=re.MULTILINE)
    ends = re.findall(r"^DTEND:(\d{8}T\d{6}Z)$", calendar, flags=re.MULTILINE)
    if len(starts) != len(ends):
        raise ValueError("trusted calendar is malformed")
    return tuple(
        (
            datetime.strptime(start, "%Y%m%dT%H%M%SZ"),
            datetime.strptime(end, "%Y%m%dT%H%M%SZ"),
        )
        for start, end in zip(starts, ends, strict=True)
    )


def _overlap(start: datetime, end: datetime, calendar: str) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in _calendar_intervals(calendar))


def _hard_ok(start: datetime, end: datetime) -> bool:
    if start.date() != end.date() or start.weekday() >= 5:
        return False
    if start.hour < 9 or end > start.replace(hour=18, minute=0, second=0):
        return False
    if end > start.replace(hour=14, minute=0, second=0):
        return False
    if start.hour < 10:
        return False
    if start.weekday() in (1, 3) and end > start.replace(hour=16, minute=30, second=0):
        return False
    if end > start.replace(hour=17, minute=0, second=0):
        return False
    lunch_start = start.replace(hour=12, minute=0, second=0)
    lunch_end = start.replace(hour=12, minute=30, second=0)
    return not (start < lunch_end and end > lunch_start)


def _earliest_valid(calendars: tuple[str, ...]) -> datetime | None:
    current = datetime(2024, 1, 15, 9, 0)
    limit = datetime(2024, 1, 19, 18, 0)
    while current <= limit:
        end = current + timedelta(hours=1)
        if _hard_ok(current, end) and not any(
            _overlap(current, end, calendar) for calendar in calendars
        ):
            return current
        current += timedelta(minutes=1)
    return None


def _check_carol_buffer(
    start: datetime,
    end: datetime,
    calendar: str,
    errors: list[str],
) -> None:
    intervals = _calendar_intervals(calendar)
    if (end.hour, end.minute) >= (16, 45):
        buffered_end = end + timedelta(minutes=15)
        if any(end < other_end and buffered_end > other_start for other_start, other_end in intervals):
            errors.append("carol_buffer_after")
    for _, other_end in intervals:
        if (other_end.hour, other_end.minute) >= (16, 45):
            if start < other_end + timedelta(minutes=15) and end > other_end:
                errors.append("carol_buffer_before")


def main() -> None:
    oracle = ScheduleOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                oracle.initialize(request)
                response = {"type": "ack"}
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence is required")
                oracle.evaluate(evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported Oracle operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
