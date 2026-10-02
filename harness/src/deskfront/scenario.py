"""Scenario data only. Both fixed and generated maps use the same controller."""
import copy

def describe(state, authored_routes=None, team="green"):
    world=state.get('world_growth',{})
    if world.get('enabled') or 'mission' in world:
        m=copy.deepcopy(world.get('mission',{}))
        routes={}
        if m:
            left,z=m['left'],m['center_z']
            for i,p in enumerate(m['spec']['support']):
                routes['front_'+str(i)]={'name':'正面射位 '+str(i+1),'points':[[left+p[0],z+p[1]]],'purpose':'support'}
            routes['flank']={'name':'外侧迂回','points':[[left+p[0],z+p[1]] for p in m['spec']['flank']],'purpose':'maneuver'}
        return dict(kind='clear_exit',active=bool(m) and m.get('status') not in ('completed','failed'),
                    goal=('阻止绿色进攻方推进，消灭绿色单位；红方是守军，不攻击红方守军，不占旗' if team=='red' else '清除本段全部守军即展开下一段；不要求到达出口，不是占旗'),routes=routes,details=m)
    return dict(kind='capture',active=True,goal='夺取目标并保持控制，避免无收益扎堆',
                routes=copy.deepcopy(authored_routes or {}),details={})
