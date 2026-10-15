"""Step 9: the internal connection phase.

Every fake used in Steps 2 to 8 is replaced here by the real component. This package owns only
the wiring (adapters.py), the composition (system.py), the synthetic Test T0 Receptor (t0.py),
a deterministic stand-in model for C (rules_model.py) and one small schema, "integration",
that maps conversation threads to the tasks they started.
"""
