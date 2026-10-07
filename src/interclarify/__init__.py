"""InterClarify: within-turn clarification for full-duplex voice agents.

P0 exposes only the engineering-preparation layer:

- :mod:`interclarify.config` -- unified configuration loader;
- :mod:`interclarify.manifest` -- reproducible run manifest;
- :mod:`interclarify.run` -- minimal run context and structured run log.

Layer 0/1/2 runtime modules are added in later phases (see
``docs/engineering_implementation.md``).
"""

from .config import config_digest, load_config, write_resolved_config
from .manifest import RunManifest, build_manifest, new_run_id
from .run import RunContext

__all__ = [
    "config_digest",
    "load_config",
    "write_resolved_config",
    "RunManifest",
    "build_manifest",
    "new_run_id",
    "RunContext",
]

__version__ = "0.1.0"
