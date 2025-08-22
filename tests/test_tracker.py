from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bt_watch import Observation, DeviceTracker


def test_new_and_lost():
    tracker = DeviceTracker(grace_seconds=10, weak_grace_seconds=20)
    base = datetime.now(timezone.utc)
    obs = Observation(base, "AA:BB:CC:DD:EE:01", "Test", "public", -50)

    tracker.new_scan()
    tracker.update(obs)
    assert tracker.finalize_scan() == []

    tracker.new_scan()
    tracker.update(obs)
    events = tracker.finalize_scan()
    assert events and events[0]["type"] == "NEW"

    lost_events = tracker.check_lost(base + timedelta(seconds=11))
    assert lost_events and lost_events[0]["type"] == "LOST"


def test_weak_signal_grace():
    tracker = DeviceTracker(grace_seconds=10, weak_grace_seconds=20)
    base = datetime.now(timezone.utc)
    obs = Observation(base, "AA:BB:CC:DD:EE:02", "Weak", "public", -95)

    tracker.new_scan()
    tracker.update(obs)
    tracker.finalize_scan()

    tracker.new_scan()
    tracker.update(obs)
    tracker.finalize_scan()

    lost = tracker.check_lost(base + timedelta(seconds=11))
    assert lost == []

    lost = tracker.check_lost(base + timedelta(seconds=21))
    assert lost and lost[0]["type"] == "LOST"


def test_no_duplicate_new_when_device_briefly_missing():
    tracker = DeviceTracker(grace_seconds=10, weak_grace_seconds=20)
    base = datetime.now(timezone.utc)
    obs1 = Observation(base, "AA:BB:CC:DD:EE:03", "Test", "public", -50)

    tracker.new_scan()
    tracker.update(obs1)
    assert tracker.finalize_scan() == []

    tracker.new_scan()
    tracker.update(obs1)
    events = tracker.finalize_scan()
    assert events and events[0]["type"] == "NEW"

    # Missing for one scan but within grace period
    tracker.new_scan()
    tracker.finalize_scan()
    tracker.check_lost(base + timedelta(seconds=1))

    # Seen again - should not emit another NEW
    tracker.new_scan()
    obs2 = Observation(base + timedelta(seconds=2), "AA:BB:CC:DD:EE:03", "Test", "public", -50)
    tracker.update(obs2)
    assert tracker.finalize_scan() == []
