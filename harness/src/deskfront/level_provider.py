"""Optional trusted level provider. No generator implementation in public Harness."""
import hashlib
import importlib.util
from pathlib import Path
import sys

PROTOCOL = 'deskfront-level-provider/v1'


def load_factory(path):
    if not path:raise ValueError('level_generator_module_required')
    source = Path(path).resolve()
    if not source.is_file():raise ValueError('level_generator_module_not_found')
    name = '_deskfront_level_plugin_' + hashlib.sha256(str(source).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, source, submodule_search_locations=[str(source.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        if getattr(module, 'PROTOCOL', None) != PROTOCOL or not callable(getattr(module, 'create_provider', None)):
            raise ValueError('level_generator_protocol_mismatch')
        return module.create_provider
    except Exception:
        sys.modules.pop(name, None)
        raise
