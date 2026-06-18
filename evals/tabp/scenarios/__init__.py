"""Scenario registry for the tabp eval harness.

Each scenario module exposes a ``META`` dict
({name, tier, goal, summary}) and a ``run()`` returning a ``Check``.
Order here is the run order.
"""

from . import screen_cvs_eval

SCENARIOS = [screen_cvs_eval]
