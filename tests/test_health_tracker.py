import time
from unittest.mock import patch
from anima.sylanne_alpha.health_tracker import SubsystemHealthTracker

def test_health_tracker_initial_state():
    tracker = SubsystemHealthTracker()
    for subsystem in ["core", "models", "memory", "autonomy", "safety"]:
        assert tracker.get_error_count_5m(subsystem) == 0
        assert tracker.get_warning_count_5m(subsystem) == 0
        assert tracker.get_status(subsystem) == "green"
        assert tracker.get_last_active(subsystem) > 0

def test_health_tracker_record_active():
    tracker = SubsystemHealthTracker()
    with patch("time.time", return_value=1000.0):
        tracker.record_active("memory")
        assert tracker.get_last_active("memory") == 1000.0

def test_health_tracker_status_transitions():
    tracker = SubsystemHealthTracker()
    
    # Core warning -> yellow
    tracker.record_warning("core")
    assert tracker.get_status("core") == "yellow"
    
    # 1 Core error -> yellow
    tracker.record_error("models")
    assert tracker.get_status("models") == "yellow"
    
    # 3 errors -> yellow
    tracker.record_error("memory")
    tracker.record_error("memory")
    tracker.record_error("memory")
    assert tracker.get_error_count_5m("memory") == 3
    assert tracker.get_status("memory") == "yellow"
    
    # 4 errors -> red
    tracker.record_error("memory")
    assert tracker.get_error_count_5m("memory") == 4
    assert tracker.get_status("memory") == "red"

def test_health_tracker_sliding_window_decay():
    tracker = SubsystemHealthTracker()
    
    # Mock time.time to simulate error events and time decay
    start_time = 2000.0
    
    with patch("time.time", return_value=start_time):
        tracker.record_error("safety") # recorded at 2000.0
        tracker.record_error("safety") # recorded at 2000.0
        tracker.record_error("safety") # recorded at 2000.0
        tracker.record_error("safety") # recorded at 2000.0
        
        assert tracker.get_error_count_5m("safety") == 4
        assert tracker.get_status("safety") == "red"
        
    # Advance time by 4 minutes (240s) -> still within 5 min window
    with patch("time.time", return_value=start_time + 240.0):
        assert tracker.get_error_count_5m("safety") == 4
        assert tracker.get_status("safety") == "red"
        
    # Advance time by 5 minutes and 1 second (301s) -> all 4 errors decay
    with patch("time.time", return_value=start_time + 301.0):
        assert tracker.get_error_count_5m("safety") == 0
        assert tracker.get_status("safety") == "green"

def test_health_tracker_mixed_decay():
    tracker = SubsystemHealthTracker()
    start_time = 5000.0
    
    # Record errors at t=5000 (1 error)
    with patch("time.time", return_value=start_time):
        tracker.record_error("autonomy")
        
    # Record more errors at t=5200 (3 errors)
    with patch("time.time", return_value=start_time + 200.0):
        tracker.record_error("autonomy")
        tracker.record_error("autonomy")
        tracker.record_error("autonomy")
        
    # Total errors is 4, status is red
    with patch("time.time", return_value=start_time + 250.0):
        assert tracker.get_error_count_5m("autonomy") == 4
        assert tracker.get_status("autonomy") == "red"
        
    # At t=5301 (301s from start_time), the first error decays. Remaining: 3. Status should become yellow.
    with patch("time.time", return_value=start_time + 301.0):
        assert tracker.get_error_count_5m("autonomy") == 3
        assert tracker.get_status("autonomy") == "yellow"
        
    # At t=5501 (301s from start_time + 200), the remaining 3 errors decay. Remaining: 0. Status green.
    with patch("time.time", return_value=start_time + 501.0):
        assert tracker.get_error_count_5m("autonomy") == 0
        assert tracker.get_status("autonomy") == "green"
