"""Whole-nine-desk intentions, selected once before parallel spatial choices.

These are design briefs, not maps, placement quotas, or allowed-card filters.
JEV chooses one programme; the builder remains free to use every current card.
Heroes are resolved from the actual selectable catalogue, never invented here.
"""
from collections import Counter, defaultdict
import copy
import hashlib
import json

from .region_graph import CELLS, PROPS
from .template_cards import cards


PURPOSE_NAMES = dict(coding='电脑工作', archive='档案', drafting='制图',
    refreshment='茶歇', packing='封装', study='阅读研究', admin='行政', hobby='手作')


# Rows are north -> south, entries west -> east. Each sequence describes an
# office workflow, not a rotation of a single all-purpose matrix.
PROGRAMMES = {
    'creation_to_output': (
        '创作到输出', '手绘与手作在接入侧汇合，电脑处理居中，打印登记与封装形成目标侧工作区。',
        'mixed_desks',
        (('drafting', 'coding', 'admin'), ('hobby', 'coding', 'packing'), ('drafting', 'hobby', 'packing'))),
    'archive_to_research': (
        '档案到研究', '资料库占北侧连续工作带，阅读查阅区与南侧制图、登记交接，书与文件器材成为主角。',
        'paper_archive',
        (('archive', 'archive', 'study'), ('study', 'study', 'admin'), ('drafting', 'archive', 'admin'))),
    'break_to_work': (
        '茶歇后回到工作', '茶歇阅读区集中在接入侧，电脑工作区位于中后段；生活物件与办公器材形成明显过渡。',
        'mixed_desks',
        (('refreshment', 'study', 'coding'), ('refreshment', 'coding', 'admin'), ('study', 'coding', 'admin'))),
    'dispatch_workshop': (
        '手作发货间', '手作备料进入封装区，后段分成发货登记与档案整理；纸盒和小工具交接而非铺满电脑。',
        'mixed_desks',
        (('hobby', 'packing', 'admin'), ('packing', 'packing', 'archive'), ('hobby', 'admin', 'archive'))),
    'reading_neighbourhood': (
        '书桌与茶歇角', '阅读桌在外围围绕中央档案核，两个茶歇角打断连续书堆；不同书籍和文件高度形成变化。',
        'paper_archive',
        (('study', 'archive', 'refreshment'), ('study', 'archive', 'study'), ('refreshment', 'study', 'study'))),
    'maker_exchange': (
        '制作与制图交接', '制图带沿北侧展开，手作区在南侧聚合，中间电脑和封装承担两个工作区的交接。',
        'small_tools',
        (('drafting', 'drafting', 'coding'), ('hobby', 'coding', 'packing'), ('hobby', 'hobby', 'packing'))),
    'office_service': (
        '办公服务中心', '中央行政带接通电脑区和档案区，接入侧保留一张茶歇桌；高器材与纸质器材分区可辨。',
        'workstations',
        (('coding', 'coding', 'archive'), ('admin', 'admin', 'archive'), ('refreshment', 'admin', 'coding'))),
    'contrasting_islands': (
        '不同用途的小岛', '六种工作用途分散相邻；电脑、书桌、茶歇与封装分别成为局部地标，靠转移形成整关关系。',
        'mixed_desks',
        (('coding', 'drafting', 'study'), ('refreshment', 'hobby', 'packing'), ('study', 'packing', 'coding'))),
    'paper_to_tools': (
        '从书纸到工具', '北侧由档案转向制图，南侧从阅读转向手作，目标侧以封装汇合；两条工作流程各有物件形态。',
        'mixed_desks',
        (('archive', 'drafting', 'packing'), ('study', 'drafting', 'packing'), ('study', 'hobby', 'hobby'))),
}

PURPOSE_ROLES = dict(
    coding='用电脑器材形成可绕行的高低遮挡', archive='用文件物件形成层次清楚的遮挡面',
    drafting='用图册和制图物件组织长短不同的掩护', refreshment='用生活物件形成短暂停靠与观望位置',
    packing='用纸盒和封装器材形成有开口的工作区', study='用不同书册形成可辨认的停靠点',
    admin='用登记与输出器材组织工作区边界', hobby='用工具与收纳物件形成错列的短掩护')


def _hero_pools(catalog):
    pools = defaultdict(set)
    for key, card in catalog.items():
        if key in ('empty', 'fortress_base'):
            continue
        actual = {item['asset'] for item in card['items']}
        pools[card['purpose']].update(asset for asset in card['hero_assets'] if asset in actual)
    return {purpose: sorted(assets) for purpose, assets in pools.items() if assets}


def _hero_groups(catalog):
    groups = defaultdict(list)
    for key, card in catalog.items():
        if key in ('empty', 'fortress_base'):
            continue
        actual = {item['asset'] for item in card['items']}
        group = list(dict.fromkeys(asset for asset in card['hero_assets'] if asset in actual))
        if group and group not in groups[card['purpose']]:
            groups[card['purpose']].append(group)
    return groups


def _materials(design):
    values = design.get('materials')
    if values is None:
        values = (design.get('material_profile') or {}).get('counts', {})
    return Counter({key: value for key, value in (values or {}).items()
        if type(value) in (int, float) and value > 0})


def _neighbours(cell):
    x, z = CELLS[cell]
    return [other for other, (ox, oz) in CELLS.items() if abs(ox-x)+abs(oz-z) == 1]


def desk_fingerprint(desks):
    """Compare positioned purposes/heroes, not the programme ID or prose.

    This is a visual-intent fingerprint, not rendered-image similarity. Role
    wording, hero ordering and a renamed/continued programme do not reset it.
    """
    if not isinstance(desks, dict) or set(desks) != set(CELLS):
        return None
    rows = [[cell, desks[cell].get('purpose'), sorted(set(desks[cell].get('hero_assets') or []))]
        for cell in CELLS]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:16]


def _root_programme(brief, programmes):
    source = brief.get('source_programme_id')
    if source and source != 'continue_recent':
        return source
    selected = brief.get('programme_id')
    if selected and selected != 'continue_recent':
        return selected
    # Older continued briefs lost their source ID. Recover only an exact
    # semantic match; otherwise unknown provenance must stay unknown.
    fingerprint = desk_fingerprint(brief.get('desks'))
    matches = [key for key, value in programmes.items() if key != 'continue_recent'
        and fingerprint and desk_fingerprint(value['desks']) == fingerprint]
    return matches[0] if len(matches) == 1 else None


def candidates(context, catalog=None):
    """Offer coherent briefs with evidence; do not choose or enforce one."""
    catalog = cards() if catalog is None else catalog
    pools = _hero_pools(catalog)
    groups = _hero_groups(catalog)
    recent = context.get('recent_designs') or []
    briefs = context.get('recent_layout_briefs') or []
    recent_materials = sum((_materials(row) for row in recent), Counter())
    latest_materials = _materials(recent[-1]) if recent else None
    result = {}

    for programme_index, (key, (name, intent, motif, rows)) in enumerate(PROGRAMMES.items()):
        purpose_by_cell = {cell: rows[z][x] for cell, (x, z) in CELLS.items()}
        # A removed purpose is an authoring incompatibility, not permission to
        # silently substitute a different desk or fabricate hero objects.
        if any(purpose not in pools for purpose in purpose_by_cell.values()):
            continue
        occurrence = Counter()
        desks = {}
        for cell, purpose in purpose_by_cell.items():
            options = groups[purpose]
            offset = (programme_index + occurrence[purpose]) % len(options)
            occurrence[purpose] += 1
            # A focus group already coexists in at least one authored card;
            # independent hero picks must not invent an impossible requirement.
            heroes = list(options[offset])
            x, _ = CELLS[cell]
            place = ('接入侧的展开停靠' if x == 0 else '中段交接与换位' if x == 1 else '目标侧接近与防守')
            neighbours = _neighbours(cell)
            same = [other for other in neighbours if purpose_by_cell[other] == purpose]
            different = [other for other in neighbours if purpose_by_cell[other] != purpose]
            relation = []
            if same:
                relation.append('与'+'、'.join(same)+'延续同一工作区')
            if different:
                relation.append('与'+'、'.join(other+'的'+PURPOSE_NAMES[purpose_by_cell[other]] for other in different)+'形成用途交接')
            desks[cell] = dict(purpose=purpose, hero_assets=heroes,
                role=place+'；'+PURPOSE_ROLES[purpose], neighbor_relation='；'.join(relation))
        result[key] = dict(name=name, programme_intent=intent, visual_motif=motif, source_programme_id=key,
            desks=desks)

    # Continuing a past programme is an explicit JEV option, not a forbidden
    # duplicate. Keep its observed intent and current valid heroes intact.
    previous = next((brief for brief in reversed(briefs)
        if set((brief.get('desks') or {})) == set(CELLS)
        and all(row.get('purpose') in pools and row.get('hero_assets')
            and any(set(row['hero_assets']) <= set(group) for group in groups[row['purpose']])
            for row in brief['desks'].values())), None)
    if previous and 3 <= len({row['purpose'] for row in previous['desks'].values()}) <= 6:
        result['continue_recent'] = dict(name='延续近期工作区',
            programme_intent='沿用最近这套九桌用途关系；搭建员仍可改变具体卡片、朝向和单物件，战术路线按本关目标调整。',
            visual_motif=previous.get('visual_motif', 'mixed_desks'),
            source_programme_id=_root_programme(previous, result),
            desks=copy.deepcopy(previous['desks']))

    recent_fingerprints = [desk_fingerprint(brief.get('desks')) for brief in briefs]
    recent_roots = [_root_programme(brief, result) for brief in briefs]
    for key, programme in result.items():
        heroes = sorted({asset for desk in programme['desks'].values() for asset in desk['hero_assets']})
        source = programme['source_programme_id']
        fingerprint = desk_fingerprint(programme['desks'])
        programme['desk_fingerprint'] = fingerprint
        consecutive = 0
        for previous_fingerprint in reversed(recent_fingerprints):
            if previous_fingerprint != fingerprint:
                break
            consecutive += 1
        programme['evidence'] = dict(
            selected_recently=(sum(root == source for root in recent_roots) if source else None),
            same_desks_recently=recent_fingerprints.count(fingerprint),
            same_desks_consecutive_in_window=consecutive,
            continuations_recently=sum(brief.get('programme_id') == 'continue_recent'
                and old_fingerprint == fingerprint
                for brief, old_fingerprint in zip(briefs, recent_fingerprints)),
            brief_history_window=len(briefs),
            recent_hero_object_counts={asset: recent_materials[asset] for asset in heroes},
            absent_from_latest_built=(sorted(set(heroes)-set(latest_materials)) if latest_materials is not None else None),
            recent_built_levels=len(recent),
            basis='实际成图物件数量；无成图证据时不把未观察当作从未出现')
    if not result:
        raise ValueError('no_catalogue_supported_desk_programme')
    return result


def model_programme(programme):
    """One board table; deterministic roles/neighbours expand after selection."""
    return dict(intent=programme['programme_intent'], source_programme_id=programme['source_programme_id'],
        desk_fingerprint=programme['desk_fingerprint'],
        columns=['cell', 'purpose', 'hero_assets'],
        desks=[[cell, *(row[key] for key in ('purpose', 'hero_assets'))]
            for cell, row in programme['desks'].items()],
        evidence=programme['evidence'])


def menu(programmes):
    def label(key, programme):
        evidence = programme['evidence']
        missing = evidence['absent_from_latest_built']
        novelty = ('尚无成图可比较' if missing is None else
            '最新成图未出现的主物件：'+('、'.join(PROPS.get(asset, {}).get('label', asset) for asset in missing) or '无'))
        return (programme['name']+'｜'+programme['programme_intent']
            + f"｜最近{evidence['brief_history_window']}关：根方案选用{evidence['selected_recently'] if evidence['selected_recently'] is not None else '未知'}次"
            + f"，同九桌用途/主物件{evidence['same_desks_recently']}次（窗口内连续{evidence['same_desks_consecutive_in_window']}次，其中续用选择{evidence['continuations_recently']}次）｜{novelty}"
            + f'｜完整九桌分工见 desk_programmes.{key}')
    return {key: label(key, value) for key, value in programmes.items()}
