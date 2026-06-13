"""Scenario registry for the acs eval harness.

Each scenario module exposes a ``META`` dict ({name, tier, goal, summary}) and a
``run()`` returning a ``harness.Check``. Order here is the run order.
"""

from . import s01_install_gate_smoke
from . import s02_create_ticket_artifacts

SCENARIOS = [
    s01_install_gate_smoke,
    s02_create_ticket_artifacts,
]
