import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIMA_DIR = os.path.join(ROOT, "anima")
if ANIMA_DIR not in sys.path:
    sys.path.insert(0, ANIMA_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
from anima.sylanne_alpha.autopoiesis import AutopoieticBoundary

class TestAutopoieticBoundary:
    def test_initial_state(self):
        boundary = AutopoieticBoundary()
        assert boundary.boundary_integrity > 0.9
        assert boundary.internal_entropy == 0.0
        assert boundary.stability() == boundary.boundary_integrity

    def test_force_decays_integrity_when_at_max(self):
        # Even if integrity is at its max (e.g. 1.0 or close), a non-zero force must decrease stability
        boundary = AutopoieticBoundary()
        # Force it to 1.0 first
        boundary.boundary_integrity = 1.0
        boundary.internal_entropy = 0.0
        
        # Apply a strong force
        force = [0.8] * 32
        res = boundary.perturb(force)
        
        # The boundary integrity must decay, and entropy must increase, causing stability to drop below 1.0
        assert res["boundary_integrity"] < 1.0
        assert res["internal_entropy"] > 0.0
        assert boundary.boundary_integrity < 1.0
        assert boundary.internal_entropy > 0.0
        assert boundary.stability() < 1.0

    def test_self_repair_cooldown_under_stress(self):
        boundary = AutopoieticBoundary()
        boundary.boundary_integrity = 1.0
        
        # Apply force that exceeds stress threshold (orth_norm * 0.6 > 0.4)
        # 0.8 force components yield orth_norm ~ 4.4, stress ~ 2.6
        force = [0.8] * 32
        boundary.perturb(force)
        
        # Verify stress is high enough to trigger open wound delay
        assert boundary._last_penetration > 0.4
        
        # self_repair should NOT restore integrity because the wound is open
        boundary.self_repair()
        assert boundary.boundary_integrity < 0.9  # Should remain at the decayed value, not healed
        
        # Verify self_repair gradually decays the stress memory
        prev_stress = boundary._last_penetration
        boundary.self_repair()
        assert boundary._last_penetration < prev_stress
