"""Source tree copy phase for staged Deskfront engines."""
from pathlib import Path
import shutil

def _copy_source_tree(root: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    # `.godot` is an editor/import cache.  It is generated for the staged
    # project and must not be copied from the source checkout (or bundled
    # into the game repository).
    for name in ('scripts', 'scenes', 'data', 'assets', 'tests'):
        if (root / name).exists():
            shutil.copytree(root / name, destination / name, dirs_exist_ok=True)
    shutil.copyfile(root / 'project.godot', destination / 'project.godot')


