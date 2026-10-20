"""Describe the current native ammunition rule without rewriting old records."""


def ammunition_rules(members):
    """The explicit native actor flag is authoritative; missing is legacy."""
    members = list(members)
    unlimited = [unit.get('ammo_infinite') is True for unit in members]
    if unlimited and all(unlimited):
        return dict(ammo_field='nominal_weapon_capacity', infinite=True,
                    reserve='unlimited', reload_enabled=False,
                    basis='native_actor_ammo_infinite', grenades='finite_inventory',
                    note='本局枪炮弹药无限，无需装填；ammo保留武器标称容量，不会因开火消耗。射击间隔、动作与原生安全检查仍有效；手雷库存单独计数。')
    if any(unlimited):
        return dict(ammo_field='per_actor_rule', infinite='per_actor',
                    reserve='unlimited', reload_enabled='per_actor',
                    basis='native_actor_ammo_infinite', grenades='finite_inventory',
                    note='逐兵看ammo_infinite：true为无限枪炮弹药、无需装填，ammo仅为标称容量；false或未提供沿用弹匣及装填规则。手雷库存单独计数。')
    return dict(ammo_field='current_magazine_rounds', reserve='unlimited',
                reload_result='refill_magazine', basis='engine_unit_reload_rule',
                note='枪械装填结束后补满弹匣，没有有限总备弹；容量和装填时长来自本局武器配置，缺失则未知；手雷数量另算。')
