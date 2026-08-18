"""Resolver package for settling answer disagreements between validated assessor positions.

This package settles *answer* disagreements between two already-validated assessor
positions. It is distinct from `agents/adjudicator/` (which performs mechanical comparison
without a model call) and from `portal/discrepancy.py` (which handles human A/B disagreements).
It deliberately takes no browser so a third independent opinion is inexpressible.
"""
