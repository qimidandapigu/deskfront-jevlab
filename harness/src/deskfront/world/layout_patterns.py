"""Whole-board, connected passage choices for the nine-desk builder.

The floor remains continuous. A closed connection places the same physical
file-wall that the existing region graph already validates and renders.
"""
from .region_graph import LIBRARY


PATTERNS = {
    'open_field': dict(label='开阔桌面：多条短路、无遮挡的中央交汇', closed=(),
        scenes=('split_lanes',)),
    'north_screen': dict(label='北侧屏障：从中南线绕入，北端形成远端阵地', closed=(
        'c0r0__c1r0', 'c0r1__c1r1', 'c1r0__c2r0'),
        scenes=('north_hook', 'offset_pockets')),
    'south_screen': dict(label='南侧屏障：从中北线绕入，南端形成远端阵地', closed=(
        'c0r2__c1r2', 'c0r1__c1r1', 'c1r2__c2r2'),
        scenes=('south_hook', 'offset_pockets')),
    'central_gate': dict(label='中央闸口：两侧被文件墙收束，中路必须争夺', closed=(
        'c0r0__c1r0', 'c0r2__c1r2', 'c1r0__c2r0', 'c1r2__c2r2'),
        scenes=('central_breach', 'defended_corner')),
    'zigzag': dict(label='折返档案区：连续转角、短射线和有限绕行', closed=(
        'c0r0__c1r0', 'c0r1__c1r1', 'c1r0__c2r0', 'c1r2__c2r2'),
        scenes=('north_hook', 'south_hook')),
    'diagonal': dict(label='错位工作岛：入口、侧路和出口呈对角交接', closed=(
        'c0r0__c0r1', 'c0r2__c1r2', 'c1r0__c1r1', 'c2r1__c2r2'),
        scenes=('offset_pockets', 'split_lanes')),
}


def connections(pattern):
    return set(LIBRARY['edges']) - set(PATTERNS[pattern]['closed'])


def menu(recent=(), scene=None):
    """Show JEV genuinely different legal skeletons, not 12 isolated booleans.

    The shortlist removes exact and near repeats only when there are other
    authored choices. JEV still chooses the submitted structure itself.
    """
    previous = [set(row.get('connections', ())) for row in recent if row.get('connections')]
    latest = previous[-1] if previous else None
    compared = previous[-2:]
    available = {name: row for name, row in PATTERNS.items()
        if all(len(connections(name) ^ old) >= 3 for old in compared)}
    if not available:
        available = {name: row for name, row in PATTERNS.items()
            if latest is None or len(connections(name) ^ latest) >= 3}
    if not available:
        available = PATTERNS
    result = {}
    for name, row in available.items():
        label = row['label'] + f'｜{len(connections(name))}条开放接口'
        if scene in row['scenes']:
            label += '｜契合本关构图'
        if latest is not None:
            label += f'｜与上关有{len(connections(name) ^ latest)}处通路不同'
        result[name] = label
    return result
