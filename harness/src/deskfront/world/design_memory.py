"""Compact, factual descriptions of built layouts for the next two JEV roles."""
from collections import Counter
import math

from .region_graph import CELLS, LIBRARY, adjacency, compile_graph, path, ports
from .fortress import RECIPE as FORTRESS_RECIPE


def card_family(module):
    """Group rotated pattern cards without pretending they are new designs."""
    if module in ('empty', 'fortress_base'):
        return module
    stem, _, turn = module.rpartition('_')
    return stem if stem and turn in ('0', '1', '2', '3') else module


def material_profile(materials, *, source='compiled_operations'):
    """Object-count evidence, not a proxy for rendered size or gameplay quality."""
    counts = Counter(materials)
    counts = Counter({asset: count for asset, count in counts.items() if count > 0})
    total = sum(counts.values())
    dominant = sorted(counts, key=lambda asset: (-counts[asset], asset))[:3]
    return dict(counts=dict(sorted(counts.items())), total=total,
        unique_types=len(counts),
        shares={asset: round(counts[asset] / total, 4) for asset in sorted(counts)},
        dominant_three=dominant,
        dominant_three_share=round(sum(counts[asset] for asset in dominant) / total, 4) if total else 0,
        source=source,
        basis=('native spec cover objects' if source=='native_spec' else 'compiled cover objects')
            + ', including closed-edge barriers and rescue walls; excludes decorative render-only props')


def material_comparison(current, reference):
    """Report reuse explicitly; never accept, reject, or rewrite a design."""
    if not current or not reference:
        return None
    a, b = Counter(current.get('materials', {})), Counter(reference.get('materials', {}))
    a, b = +a, +b
    shared_types = set(a) & set(b)
    all_types = set(a) | set(b)
    shared_count = sum(min(a[asset], b[asset]) for asset in shared_types)
    total_a, total_b = sum(a.values()), sum(b.values())
    return dict(shared_types=sorted(shared_types),
        type_jaccard=round(len(shared_types) / len(all_types), 4) if all_types else None,
        shared_object_count=shared_count,
        shared_object_share_current=round(shared_count / total_a, 4) if total_a else None,
        shared_object_share_reference=round(shared_count / total_b, 4) if total_b else None,
        current_objects_using_reference_assets_share=round(
            sum(a[asset] for asset in shared_types) / total_a, 4) if total_a else None,
        basis='asset types and object counts only; not a visual similarity percentage')


def _cell_props(operations, cells, compiled_covers):
    """Attribute the compiler's final objects without reimplementing edits.

    compile_graph emits surviving card components in CELLS order, then edge
    barriers, then place_prop objects. Using these ranges also preserves the
    owning cell when a legacy rotated component extends across its boundary.
    """
    removed = {(op['cell'], op['index']) for op in operations
        if op.get('op') == 'edit_component' and op.get('action') == 'remove'}
    added = [op for op in operations if op.get('op') == 'place_prop']
    result = {}
    cursor = 0
    for cell in CELLS:
        part = LIBRARY['cells'][cell][cells[cell]['card']]
        count = sum((cell, index) not in removed for index in range(len(part['covers'])))
        result[cell] = [row[4] for row in compiled_covers[cursor:cursor + count]]
        cursor += count
    if added:
        for op, row in zip(added, compiled_covers[-len(added):]):
            result[op['cell']].append(row[4])
    for cell, data in cells.items():
        if data['card'] == 'fortress_base':
            result[cell].extend(row[4] for row in FORTRESS_RECIPE['covers'])
    return result


def _native_covers(actual_spec):
    """Accept a complete native cover list, including a legitimately empty one."""
    if not isinstance(actual_spec, dict) or not isinstance(actual_spec.get('covers'), list):
        return None
    covers = actual_spec['covers']
    if any(not isinstance(row, (list, tuple)) or len(row)<6 or not isinstance(row[4], str)
           or any(type(row[index]) not in (int, float) or not math.isfinite(row[index])
                  for index in (0, 1, 2, 3, 5)) for row in covers):
        return None
    return covers


def _native_cell_props(cells, covers):
    """Use old physical centers, never today's component ordering or quantity."""
    result = {cell: [] for cell in cells}
    other = dict(edge_barriers=Counter(), fortress_walls=Counter(), unassigned=Counter())
    for row in covers:
        if row[4] == 'fort_wall':
            other['fortress_walls'][row[4]] += 1
            continue
        if any(row[4] == edge['barrier'][4]
               and all(abs(row[i]-edge['barrier'][i])<.0001 for i in range(4))
               for edge in LIBRARY['edges'].values()):
            other['edge_barriers'][row[4]] += 1
            continue
        owners = [cell for cell in cells
            if abs(row[0]-(CELLS[cell][0]*.6+.3)) < .3-.000001
            and abs(row[1]-(CELLS[cell][1]-1)*.7) < .35-.000001]
        if len(owners) == 1:
            result[owners[0]].append(row[4])
        else:
            other['unassigned'][row[4]] += 1
    return result, {name: dict(sorted(counts.items())) for name, counts in other.items() if counts}


def describe(operations, *, option=None, mission=None, tactical=None, actual_spec=None):
    """Describe what was submitted, including the actual edited prop geometry."""
    if not operations:
        return None
    # Godot's JSON snapshots serialize integral operation fields as 0.0. This
    # is a read-only normalization for Python's stricter compiler, not a rewrite
    # of the construction command or the JEV-selected layout.
    operations=[dict(op,**{key:int(op[key]) for key in ('rotation','index')
        if type(op.get(key)) is float and op[key].is_integer()}) for op in operations]
    native_covers = _native_covers(actual_spec)
    cells = {}
    entry = exit_cell = deployment = None
    edges = []
    for op in operations:
        kind = op.get('op')
        if kind == 'set_ports':
            entry, exit_cell = op.get('entry'), op.get('exit')
        elif kind == 'place_region' and op.get('cell') in CELLS:
            module = op.get('module')
            if module not in LIBRARY['cells'][op['cell']] and native_covers is None:
                continue
            cells[op['cell']] = dict(card=module, rotation=op.get('rotation', 0),
                family=card_family(module))
        elif kind == 'connect_regions':
            edges.append(op.get('edge'))
        elif kind == 'deploy':
            deployment = op.get('module')
    if not cells:
        return None
    # The compiler applies individual add/move/remove/replace operations. Its
    # result is a more truthful material fingerprint than the card names alone.
    if native_covers is None:
        spec = compile_graph(operations)
        actual_props = _cell_props(operations, cells, spec['covers'])
        material_counts = Counter(cover[4] for cover in spec['covers'])
        if any(part['card']=='fortress_base' for part in cells.values()):
            material_counts.update(cover[4] for cover in FORTRESS_RECIPE['covers'])
        source = 'compiled_operations'
        other_materials = None
    else:
        # The recorded geometry is authoritative even if a card's current
        # library footprint, edit indices, or rescue recipe have since changed.
        spec = actual_spec
        actual_props, other_materials = _native_cell_props(cells, native_covers)
        material_counts = Counter(cover[4] for cover in native_covers)
        source = 'native_spec'
    for cell, data in cells.items():
        part = LIBRARY['cells'][cell].get(data['card'], {})
        props = actual_props[cell]
        data['props'] = props
        data['props_basis'] = ('native cover centers; edge and fortress walls reported separately'
            if native_covers is not None else 'compiled components and edits')
        data['visual_identity'] = dict(
            family=part.get('family', data['family']),
            theme=part.get('theme'),
            hero_assets=[asset for asset in part.get('hero_assets', []) if asset in props],
            material_counts=dict(sorted(Counter(props).items())),
            basis='current catalog family/theme; observed material counts' if native_covers is not None
                else 'current compiled design')
    materials = dict(sorted(material_counts.items()))
    route = spec.get('design_card') or {}
    if native_covers is not None and 'main_regions' not in route:
        # Topology belongs to the submitted connections, not to the current
        # library's possibly different item count or collision geometry.
        route_entry, route_exit = ports(operations)
        graph = adjacency({cell: data['card'] for cell, data in cells.items()}, edges)
        main = path(graph, route_entry, route_exit)
        flank = next((alternate for cell in main[1:-1]
            if (alternate := path(graph, route_entry, route_exit, cell))), [])
        route = dict(route, entry_cell=route_entry, exit_cell=route_exit,
            main_regions=main, flank_regions=flank)
    result = dict(option=option, mission=mission, entry=entry or route.get('entry_cell'),
        exit=exit_cell or route.get('exit_cell'), deployment=deployment,
        cells={cell: cells[cell] for cell in CELLS if cell in cells},
        connections=sorted(edge for edge in edges if edge), materials=materials,
        material_profile=material_profile(materials, source=source),
        main_route=route.get('main_regions', []), flank_route=route.get('flank_regions', []))
    if other_materials is not None:
        result['non_cell_materials'] = other_materials
    if tactical:
        result['static_exposure'] = {name: (tactical.get(name) or {}).get('exposed_fraction')
            for name in ('main', 'flank')}
    return result


def similarity(left, right):
    """Legacy composition/route score, not visual acceptance or a veto."""
    if not left or not right:
        return None
    shared = set(left['cells']) | set(right['cells'])
    family = sum(left['cells'].get(cell, {}).get('family') ==
        right['cells'].get(cell, {}).get('family') for cell in shared) / len(shared)
    a, b = Counter(left['materials']), Counter(right['materials'])
    names = set(a) | set(b)
    materials = sum(min(a[name], b[name]) for name in names) / max(1,
        sum(max(a[name], b[name]) for name in names))
    le, re = set(left['connections']), set(right['connections'])
    topology = len(le & re) / max(1, len(le | re))
    ports = (int(left['entry'] == right['entry']) + int(left['exit'] == right['exit'])) / 2
    return round(.35 * family + .30 * materials + .25 * topology + .10 * ports, 3)
