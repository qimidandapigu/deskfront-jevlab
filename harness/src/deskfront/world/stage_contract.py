"""Stable staging hook primitives shared by pipeline phases and tests."""

PASSING_HOOK = dict(name="consistent local passing side",
    before="var steered=target+apart.normalized()*(space-apart.length())*.8",
    after="var steered=preload(\"res://scripts/formation_stability.gd\").separation(self,other,target,space,game.elapsed)\n\t\t\t\t\t\tif not game.field.segment_walkable(pos(),steered) or not game.field.segment_walkable(steered,target):steered=target")


def apply_hooks(source, patches):
    for patch in patches:
        count=source.count(patch["before"])
        if count != 1:
            if count == 0 and patch.get("optional",False):
                continue
            raise RuntimeError(f"World hook {patch.get('name','unnamed')} expected one anchor, found {count}")
        source=source.replace(patch["before"],patch["after"],1)
    return source
