"""Presentation-only hooks: damage and swept collision remain in native CombatFX."""
from .stage import apply_hooks


def install(source):
    trail = ('\t\tp.trail-=dt\n\t\tif p.trail<=0:\n\t\t\tp.trail=.045\n'
             '\t\t\tbeam(previous,next,.006 if p.weapon in ["rocket","cannon","at_cannon"] else .003,Color(1,.80,.36),.22)\n'
             '\t\t\tif p.weapon in ["rocket","cannon","at_cannon"]:puff(previous,.035,.7,true)')
    return apply_hooks(source, [dict(name='artillery shell setup on actual launch',
        before='\n\treturn true\n\nfunc trace(',
        after='\n\tpreload("res://scripts/artillery_presentation.gd").setup(self,projectiles[-1])\n\treturn true\n\nfunc trace('),
        dict(name='mortar muzzle flash follows the launch tangent',
             before='\tbeam(from,from+dir*.045,.009 if explosive else .006,Color(1,.91,.53),.10)',
             after='\tif cfg.get("harness_mortar",false):dir=preload("res://scripts/artillery_presentation.gd").launch_tangent({"from":from,"to":end,"cfg":cfg})\n'
                   '\tbeam(from,from+dir*.045,.009 if explosive else .006,Color(1,.91,.53),.10)'),
        dict(name='continuous artillery trail on swept collision path', before=trail,
             after='\t\tif preload("res://scripts/artillery_presentation.gd").handles(p):\n'
                   '\t\t\tpreload("res://scripts/artillery_presentation.gd").step(self,p,previous,next,dt)\n'
                   '\t\telse:\n' + '\n'.join('\t'+line for line in trail.splitlines()))])
