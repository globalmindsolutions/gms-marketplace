"""Scenario registry for the acs eval harness.

Each scenario module exposes a ``META`` dict ({name, tier, goal, summary}) and a
``run()`` returning a ``harness.Check``. Order here is the run order.
"""

from . import s01_install_gate_smoke
from . import s02_create_ticket_artifacts
from . import s03_resume_and_verify
from . import s04_skill_triggers
from . import s05_session_end
from . import s06_update_migration
from . import s07_fanout_tracker_sync

SCENARIOS = [
    s01_install_gate_smoke,
    s02_create_ticket_artifacts,
    s03_resume_and_verify,
    s04_skill_triggers,
    s05_session_end,
    s06_update_migration,
    s07_fanout_tracker_sync,
]
