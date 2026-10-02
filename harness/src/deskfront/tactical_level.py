"""Data-only route-choice arena for the existing Deskfront surface."""
ROUTES = {
    'left': {'name': '左路：连续遮挡，绕行较长', 'points': [[-.12, 2.95], [-.12, 2.5], [-.12, 2.05], [.12, 1.8], [.45, 1.95]]},
    'center': {'name': '中路：交替掩体，接近距离短', 'points': [[.54, 2.95], [.54, 2.65], [.54, 2.35], [.54, 2.15]]},
    'right': {'name': '右路：侧面接近，开放区更长', 'points': [[1.13, 2.95], [1.13, 2.5], [1.13, 2.05], [.83, 1.85], [.62, 2.0]]},
}


def specification():
    from scenario_authoring import example
    spec = example()
    spec.update(base_map=2, name='三路前哨 · 3 对 5',
                briefing='左路连续遮挡，中路交替掩体，右路有开放段。敌军初始为两名前哨、两名后卫和一名侧翼兵；开战后由原生 AI 自由行动。路线只是选择，不保证安全。',
                tactical_plan=['选择交战路线，不强制使用侧翼', '先建立射界，再判断推进风险', '受阻时允许转移至另一条路线'],
                objective=[.54, 2.15], hold_seconds=60,
                spawns=[[.54, 3.22], [-.18, .87], [.54, 1.05]])
    rows = [(.12, 2.9, 90, .32), (.12, 2.48, 90, .32), (.12, 2.06, 90, .32), (.12, 1.64, 90, .24),
            (.36, 2.82, 0, .25), (.73, 2.48, 0, .25), (.34, 2.23, 0, .22),
            (.97, 2.84, 90, .25), (.97, 1.82, 90, .25),
            (.39, 1.48, 0, .23), (.77, 1.36, 0, .23), (.54, 3.03, 0, .25)]
    spec['covers'] = [dict(kind='sandbag', position=[x,z], size=[length,.085,.055], yaw=yaw) for x,z,yaw,length in rows]
    return spec
