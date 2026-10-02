"""Read-only model views. Never change the submitted design or engine geometry."""
import copy
from collections import Counter


def design_view(design):
    """Share repeated evidence labels; preserve observed objects and outcomes."""
    view = copy.deepcopy(design)
    if not isinstance(view, dict):
        return view
    bases = {}
    for cell, data in view.get('cells', {}).items():
        if 'props_basis' in data:
            bases[cell] = data.pop('props_basis')
        identity = data.get('visual_identity') or {}
        if 'props' in data and identity.get('material_counts') == dict(Counter(data['props'])):
            identity.pop('material_counts')
    if bases:
        view['cell_material_basis'] = next(iter(bases.values())) if len(set(bases.values())) == 1 else bases
    profile = view.get('material_profile') or {}
    if 'materials' in view and profile.get('counts') == view['materials']:
        profile.pop('counts')
    return view


def planner_view(context):
    view = copy.deepcopy(context)
    for key in ('current_design',):
        if key in view:
            view[key] = design_view(view[key])
    if 'recent_designs' in view:
        view['recent_designs'] = [design_view(row) for row in view['recent_designs']]
    return view


def builder_view(context):
    view = planner_view(context)
    if view.get('stage') in ('layout_draft', 'batch_revision'):
        catalog = view.get('asset_catalog')
        if (view.get('asset_columns') == ['name', 'width', 'depth', 'height']
                and isinstance(catalog, dict)
                and all(isinstance(row, list) and len(row) == 4 for row in catalog.values())):
            # Every card item still has its exact dimensions and field names.
            # Keep the asset-name dictionary for readable IDs; full inventory
            # dimensions are needed again when editing an individual item.
            view['asset_catalog'] = {asset: [row[0]] for asset, row in catalog.items()}
            view['asset_columns'] = ['name']
    task = view.get('task', {})
    if task.get('spatial_goal'):
        view['task'] = {key: task[key] for key in (
            'option', 'mission_kind', 'forces', 'defender_mix', 'support_type',
            'route_preference', 'spatial_goal') if key in task}
    return view
