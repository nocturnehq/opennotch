"""Find the next timed meeting in a local iCalendar export.

One-off events, explicit recurrence dates, and ordinary daily through yearly
rules are supported. All-day events, very dense rules and range overrides
are skipped so the countdown never guesses a start time for them.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import stat
import threading

import gi

MAX_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 4000
MAX_ITERATIONS = 4096
_LOOKUP_LOCK = threading.Lock()


@dataclass(frozen=True)
class Meeting:
    title: str
    starts_at: datetime


def _read_calendar(path):
    # Opening a selected FIFO should never block the calendar worker.
    fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Choose a regular iCalendar file.")
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("The iCalendar file exceeds 2 MiB.")
    if b"\x00" in data:
        raise ValueError("The iCalendar file is not UTF-8 text.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("The iCalendar file is not UTF-8 text.") from exc


def _bindings():
    try:
        gi.require_version("ICalGLib", "3.0")
        from gi.repository import GLib, ICalGLib
    except (ValueError, ImportError) as exc:
        raise ValueError("Calendar support requires libical-glib 3.0.") from exc
    return GLib, ICalGLib


class _Calendar:
    def __init__(self, data, local_zone):
        glib, self.ical = _bindings()
        local_name = local_zone or glib.TimeZone.new_local().get_identifier()
        self.local_zone = self.ical.Timezone.get_builtin_timezone(local_name)
        if self.local_zone is None:
            if local_zone:
                raise ValueError("Choose a recognized calendar time zone.")
            self.local_zone = self.ical.Timezone.get_utc_timezone()
        try:
            self.calendar = self.ical.Component.new_from_string(data)
        except TypeError as exc:
            raise ValueError("Choose an iCalendar (.ics) export.") from exc
        kind = self.ical.ComponentKind.VCALENDAR_COMPONENT
        if self.calendar is None or self.calendar.isa() != kind:
            raise ValueError("Choose an iCalendar (.ics) export.")
        self.event_kind = self.ical.ComponentKind.VEVENT_COMPONENT
        if self.calendar.count_components(self.event_kind) > MAX_EVENTS:
            raise ValueError(f"The iCalendar file exceeds {MAX_EVENTS} events.")
        self.properties = self.ical.PropertyKind
        self.zones = {}

    def _properties(self, event, kind):
        prop = event.get_first_property(kind)
        while prop is not None:
            yield prop
            prop = event.get_next_property(kind)

    def _time(self, prop, value):
        if value is None or value.is_null_time() or value.is_date() or not value.is_valid_time():
            return None
        if value.is_utc():
            return value
        tzid = prop.get_parameter_as_string("TZID")
        if tzid:
            if tzid not in self.zones:
                self.zones[tzid] = (self.calendar.get_timezone(tzid)
                                    or self.ical.Timezone.get_builtin_timezone(tzid)
                                    or self.ical.Timezone.get_builtin_timezone_from_tzid(tzid))
            zone = self.zones[tzid]
        else:
            zone = self.local_zone
        if zone is None:
            return None
        value.set_timezone(zone)
        return value

    @staticmethod
    def _timestamp(value):
        if value is None:
            return None
        return value.as_timet_with_zone(value.get_timezone())

    def _cancelled(self, event):
        status = event.get_first_property(self.properties.STATUS_PROPERTY)
        return status is not None and status.get_value_as_string() == "CANCELLED"

    def _events(self):
        """Choose the latest revision of each master and detached occurrence."""
        series = {}
        overrides = {}
        unsupported = set()
        events = []
        event = self.calendar.get_first_component(self.event_kind)
        while event is not None and len(events) < MAX_EVENTS:
            events.append(event)
            event = self.calendar.get_next_component(self.event_kind)
        for index, event in enumerate(events):
            uid = event.get_uid() or index
            recurrence = event.get_first_property(self.properties.RECURRENCEID_PROPERTY)
            if recurrence is None:
                previous = series.get(uid)
                if previous is None or event.get_sequence() >= previous.get_sequence():
                    series[uid] = event
            elif recurrence.get_parameter_as_string("RANGE"):
                unsupported.add(uid)
            else:
                original = self._timestamp(self._time(recurrence, recurrence.get_recurrenceid()))
                if original is None:
                    unsupported.add(uid)
                else:
                    revisions = overrides.setdefault(uid, {})
                    previous = revisions.get(original)
                    if previous is None or event.get_sequence() >= previous.get_sequence():
                        revisions[original] = event

        for uid, event in series.items():
            if uid not in unsupported and not self._cancelled(event):
                yield event, overrides.get(uid, {})
        for uid, revisions in overrides.items():
            if uid in unsupported or (uid in series and self._cancelled(series[uid])):
                continue
            for event in revisions.values():
                if not self._cancelled(event):
                    yield event, {}

    def _recur(self, start, prop, lower, upper, budget, excluded):
        fields = {field.partition("=")[0] for field in (prop.get_value_as_string() or "").upper().split(";")}
        if fields & {"BYHOUR", "BYMINUTE", "BYSECOND"}:
            return
        rule = prop.get_rrule()
        frequency = self.ical.RecurrenceFrequency
        if (rule is None or rule.get_freq() not in (frequency.DAILY_RECURRENCE, frequency.WEEKLY_RECURRENCE,
                                                     frequency.MONTHLY_RECURRENCE, frequency.YEARLY_RECURRENCE)
                or rule.get_count() > MAX_ITERATIONS):
            return
        try:
            iterator = self.ical.RecurIterator.new(rule, start)
        except TypeError:
            return
        if iterator is None:
            return
        if not rule.get_count() and self._timestamp(start) < lower:
            lower_time = self.ical.Time.new_from_timet_with_zone(int(lower), 0, start.get_timezone())
            if not iterator.set_start(lower_time):
                return
        while budget[0]:
            budget[0] -= 1
            occurrence = iterator.next()
            if occurrence is None or occurrence.is_null_time():
                return
            stamp = occurrence.as_timet_with_zone(start.get_timezone())
            if stamp > upper:
                return
            if stamp >= lower and stamp not in excluded:
                yield stamp
                return

    def _starts(self, event, lower, upper, budget, excluded):
        # EXRULE is obsolete. Skip the event when an excluded occurrence cannot be inferred.
        if event.get_first_property(self.properties.EXRULE_PROPERTY):
            return
        prop = event.get_first_property(self.properties.DTSTART_PROPERTY)
        if prop is None:
            return
        start = self._time(prop, prop.get_dtstart())
        if start is None:
            return
        yield self._timestamp(start)
        if event.get_first_property(self.properties.RECURRENCEID_PROPERTY):
            return
        for date in self._properties(event, self.properties.RDATE_PROPERTY):
            entry = date.get_rdate()
            when = entry.get_time()
            if when.is_null_time():
                when = entry.get_period().get_start()
            stamp = self._timestamp(self._time(date, when))
            if stamp is not None:
                yield stamp
        for rule in self._properties(event, self.properties.RRULE_PROPERTY):
            yield from self._recur(start, rule, lower, upper, budget, excluded)

    def next(self, lower, upper):
        soonest = None
        upper_bound = upper
        budget = [MAX_ITERATIONS]
        for event, overrides in self._events():
            excluded = set(overrides)
            for date in self._properties(event, self.properties.EXDATE_PROPERTY):
                value = self._time(date, date.get_exdate())
                if value is not None:
                    excluded.add(self._timestamp(value))
            best_stamp = None
            for stamp in self._starts(event, lower, upper_bound, budget, excluded):
                if lower <= stamp <= upper_bound and stamp not in excluded:
                    best_stamp = upper_bound = stamp
            if best_stamp is not None:
                title = " ".join((event.get_summary() or "Untitled meeting").split())[:160]
                soonest = Meeting(title or "Untitled meeting", datetime.fromtimestamp(best_stamp, timezone.utc))
        return soonest


def next_meeting(path, now=None, *, local_zone=None, horizon_days=30):
    """Return the next timed Meeting with a UTC start, or None within the horizon.

    Parse on a worker thread. Invalid or oversized exports raise ValueError and
    an unreadable file raises OSError. The file is opened locally without writes.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None or not 1 <= horizon_days <= 90:
        raise ValueError("The calendar lookup needs an aware time and a 1–90 day horizon.")
    data = _read_calendar(path)
    lower = now.timestamp()
    upper = (now.astimezone(timezone.utc) + timedelta(days=horizon_days)).timestamp()
    with _LOOKUP_LOCK:
        calendar = _Calendar(data, local_zone)
        method = calendar.calendar.get_first_property(calendar.properties.METHOD_PROPERTY)
        if method is not None and method.get_value_as_string() == "CANCEL":
            return None
        return calendar.next(lower, upper)
