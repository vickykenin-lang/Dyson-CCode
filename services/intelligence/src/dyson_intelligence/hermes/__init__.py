"""Isolated Hermes runtime (zone 4): a candidate intelligence engine.

This package is what runs inside the Hermes container. It may import only dyson_contracts, the
provider-neutral shapes in dyson_intelligence.models and itself: no database driver, no network
library, no model SDK, no secret store, no audit or evidence writer (tests enforce this). Its only
ways out are the two ports it is handed: C for models and G for tools.
"""
