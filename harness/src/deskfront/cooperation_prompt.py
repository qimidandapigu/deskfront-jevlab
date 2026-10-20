"""Provider-only semantic comparison of complete squad choices.

Binding retains full original execution dictionaries. This projection neither
creates native input nor queries the game/model. Current physical/safety/task
state is preserved; repeated proposal diagnostics and route derivations are not
part of the decision view.
"""
import copy
import json

SCHEMA='cooperation-decision-view/v1'
INSTRUCTIONS='''\n# 平行方案事实表
本题键与cooperation_candidates一一对应，一次选完整方案；bindings明确每名成员的角色、路线及是否保留原令，所选路线核心事实只在member_region_choices出现一次。比较表列名在cooperation_comparison_contract；行内直接列谁针对哪个已知威胁帮谁、双方路程、当前原生可攻击、未来二维机会、切换火力、角度及风险。comparison_current_members只保存一份各兵当前火力；逐关系current_native保留检查时刻和枪口依据。
relevance.supported仅表示同目标二维几何有关，不是已形成支援；current_native与endpoint_2d不可互换。未知不等于false、零代价或安全。路径长度与射程沿用原生世界单位，position为图坐标；没有原生时序就不知道支援建立时间，不能从路程编ETA或先后保证。逐目标route_geometry仅是提供的二维样点计数，不证明敌方射界、整路隐藏或安全。
保持当前任务、个人短动作交接、失败、权限和原截止，普通重评不重置任务。支援未形成不阻止队友合法移动，原生射界、发射、伤害和压制分别判断；选中不等于执行成功。比较直接推进、保持和配合的实际取舍，不为战术名强行配合；每个完整计划单独选择，不合计同类概率替模型改选。
'''


def _text(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def _routes(facts):
    columns=facts.get('route_columns')
    result={}
    for uid,menu in facts.get('member_region_choices',{}).items():
        if not isinstance(menu,dict):continue
        result[uid]={}
        for rid,row in menu.items():
            if isinstance(row,dict):result[uid][rid]=copy.deepcopy(row)
            elif columns and isinstance(row,list):
                result[uid][rid]={key:copy.deepcopy(value) for key,value in zip(columns,row)
                                 if value!={'missing':True}}
    return result


def _project_route(row):
    # Exact deletion whitelist: only derived duplicated comparison blocks are
    # replaced below. Unknown/future fields survive rather than hiding a new
    # route constraint. Original full geometry stays private in Binding.
    result=copy.deepcopy(row)
    for key in ('relation','contact_approach','endpoint_obstructions','close_engagement','route_comparison'):
        result.pop(key,None)
    comparison=row.get('route_comparison')
    if isinstance(comparison,dict):
        result['route_comparison']={key:copy.deepcopy(value) for key,value in comparison.items()
                                    if key!='shorter_same_target_checks'}
    targets={}
    for item in row.get('endpoint_obstructions',[]) or []:
        if not isinstance(item,dict) or not item.get('target_id'):continue
        targets.setdefault(item['target_id'],{}).update({key:copy.deepcopy(value) for key,value in item.items()
                                                        if key!='target_id'})
    for item in (row.get('close_engagement') or {}).get('targets',[]):
        if not isinstance(item,dict) or not item.get('target_id'):continue
        target=targets.setdefault(item['target_id'],{})
        for key,value in item.items():
            if key!='target_id':target['route_geometry' if key=='geometry' else key]=copy.deepcopy(value)
    nearest=row.get('contact_approach') or {}
    if isinstance(nearest,dict) and nearest.get('target_id'):
        target=targets.setdefault(nearest['target_id'],{})
        # The same-target distance/range/gain already appears in exact endpoint
        # facts. Keep only fields absent there; no nearest-contact claim is
        # silently applied to another relation's enemy.
        endpoint=target.get('endpoint',{})
        for source,dest in (('destination_distance','distance'),('in_weapon_range','in_weapon_range')):
            if source in nearest and dest not in endpoint:
                target.setdefault('endpoint',{})[dest]=copy.deepcopy(nearest[source])
        for key in ('range_fit','distance_gain','firing_line'):
            if key in nearest and key not in target:target[key]=copy.deepcopy(nearest[key])
    if targets:result['target_facts']=targets
    return result


def _route_table(routes):
    columns=list(dict.fromkeys(k for menu in routes.values() for row in menu.values() for k in row))
    packed={uid:{rid:[copy.deepcopy(row[k]) if k in row else {'missing':True} for k in columns]
                 for rid,row in menu.items()} for uid,menu in routes.items()}
    return (packed,columns) if len(_text(packed))+len(_text(columns))<len(_text(routes)) else (routes,None)


def _endpoint(row):
    if not isinstance(row,dict):return copy.deepcopy(row)
    # These statements are repeated constants, stated once in the contract.
    return {key:copy.deepcopy(value) for key,value in row.items()
            if key not in ('distance_basis',) and not(key=='native_muzzle' and value=='unverified')}


def _criterion(key,candidate):
    roles=[]
    for uid,row in candidate.get('bindings',{}).items():
        roles.append(uid+(':保留原令' if row.get('keep_assignment') else ':'+str(row.get('role','unknown'))+'@'+str(row.get('route_id','unknown'))))
    links=[','.join(map(str,row.get('supporter_ids',[])))+'→'+','.join(map(str,row.get('assisted_member_ids',[])))+'@'+','.join(map(str,row.get('threat_ids',[])))
           for row in candidate.get('support_relations',[])]
    hold=candidate.get('hold_contract')
    return str(candidate.get('intent','unknown'))+'｜'+','.join(roles)+'｜支援='+(';'.join(links) if links else '无指定关系')+('｜守备='+_text(hold) if hold else '')+('｜装备='+_text(candidate['equipment']) if candidate.get('equipment') else '')+'｜对照='+key


def _role_facts(facts,current):
    members=[]
    for row in facts.get('members',[]):
        uid=row.get('member_id')
        current.setdefault(uid,dict(current_attackable_target_ids=copy.deepcopy(row.get('current_attackable_target_ids')),
                                    current_fire=copy.deepcopy(row.get('current_fire'))))
        members.append([uid,row.get('route_cost'),copy.deepcopy(row.get('endpoint')),copy.deepcopy(row.get('risks'))])
    relationships=[]
    for row in facts.get('relationships',[]):
        relevance=row.get('relevance',{})
        relevance={key:copy.deepcopy(value) for key,value in relevance.items() if key!='scope'} if isinstance(relevance,dict) else copy.deepcopy(relevance)
        relationships.append([
            row.get('supporter_id'),row.get('mover_id'),row.get('threat_id'),relevance,
            copy.deepcopy(row.get('current_native')),_endpoint(row.get('endpoint_2d')),
            _endpoint(row.get('mover_endpoint_2d')),copy.deepcopy(row.get('route_costs')),
            row.get('target_switch'),copy.deepcopy(row.get('angles')),copy.deepcopy(row.get('risks'))])
    return dict(members=members,relationships=relationships,
                shared_endpoints=copy.deepcopy(facts.get('shared_endpoints',[])),
                relation_rows_omitted=facts.get('relation_rows_omitted',0))


def prepare_model_view(state,facts,candidates):
    """Return compact provider state, exact-key criteria, additional rules.

    No execution dictionary is reconstructed here. Ordinary current state and
    all unknown top-level constraints stay intact. Deletions are explicitly
    limited to the proposal display and selected-route derivations above.
    """
    from coordinate_prompt import unshare
    view=unshare(state)
    view.pop('cooperation_candidates',None)
    if isinstance(view.get('prompt_contract'),dict):view['prompt_contract'].pop('shared_instructions',None)
    available=_routes(facts)
    used={uid:set() for uid in available}
    for candidate in candidates.values():
        for uid,binding in candidate.get('bindings',{}).items():
            if binding.get('route_id') in available.get(uid,{}):used.setdefault(uid,set()).add(binding['route_id'])
    selected={uid:{rid:_project_route(row) for rid,row in menu.items() if rid in used.get(uid,set())}
              for uid,menu in available.items()}
    packed,columns=_route_table(selected)
    view['member_region_choices']=packed
    view.pop('route_columns',None)
    if columns is not None:view['route_columns']=columns

    current,guards,displayed={},{},{}
    observed_guards={}
    for candidate in candidates.values():
        for uid,binding in candidate.get('bindings',{}).items():
            expected={field:binding[field] for field in ('expected_assignment_id','expected_local_action_revision') if field in binding}
            observed_guards.setdefault(uid,[]).append(expected)
    for uid,values in observed_guards.items():
        if values and values[0] and all(value==values[0] for value in values):guards[uid]=copy.deepcopy(values[0])
    for key,candidate in candidates.items():
        row=copy.deepcopy(candidate)
        # Build diagnostics/label and aggregate scoring are not permissions or
        # observed effects. The actual complete Binding is retained unchanged.
        for field in ('label','probe_coverage','proposal_basis','candidate_reduction'):
            row.pop(field,None)
        if row.get('candidate_id')==key:row.pop('candidate_id')
        for uid,binding in row.get('bindings',{}).items():
            # Share only guards actually present and equal on every option.
            # Different/missing guards remain explicit rather than filling an
            # unknown revision from another proposal for the same actor.
            if uid in guards:
                for field in guards[uid]:binding.pop(field,None)
        for relation in row.get('support_relations',[]):
            for field,binding_field in (('route_ids','route_id'),('region_ids','region_id')):
                mapping=relation.get(field)
                if isinstance(mapping,dict) and all(uid in row.get('bindings',{}) and row['bindings'][uid].get(binding_field)==value for uid,value in mapping.items()):relation.pop(field)
            if relation.get('expected_opportunity')=='endpoint_2d_clear_in_range_native_fire_unverified':relation.pop('expected_opportunity')
        comparison=row.get('comparison',{})
        if isinstance(comparison,dict) and isinstance(comparison.get('role_facts'),dict):
            row['comparison']={'role_facts':_role_facts(comparison['role_facts'],current)}
        displayed[key]=row
    view['comparison_current_members']=current
    view['cooperation_comparison_contract']=dict(
        schema=SCHEMA,
        authority='one_provider_choice_complete_raw_binding_unchanged',
        member_columns=['member_id','route_cost_native','endpoint','risks'],
        relationship_columns=['supporter','mover','known_threat','same_target_geometry_relevance',
                              'current_native','future_support_endpoint_2d','future_mover_endpoint_2d',
                              'route_costs_native','target_switch','angles_deg','risks'],
        route_scope='only_routes_referenced_by_offered_complete_plans',
        omitted_route_count=sum(len(menu)-len(used.get(uid,set())) for uid,menu in available.items()),
        current_state='mission_strategy_safety_permissions_failures_handover_original_deadlines_preserved',
        admission_guards=guards,
        relation_routes='omitted_route_ids_or_region_ids_equal_this_plan_bindings',
        endpoint_native_muzzle='unverified_unless_explicit_native_check',
        eta='unknown_without_native_route_timing',
        actual_assistance_effect='unverified_unless_native_attribution_supplied',
        geometry_relevance='same_target_2d_only_not_enemy_attack_or_safety',
        support_is_movement_gate=False,
        probabilities='individual_complete_plan_no_family_aggregation',
        display_omissions=['unused_route_menu','proposal_label','probe_coverage','proposal_basis','candidate_reduction',
                          'aggregate_comparison_replaced_by_role_facts','redundant_route_nearest_contact',
                          'shorter_same_target_checks_not_selected','constant_relationship_interpretations'])
    view['cooperation_candidates']=displayed
    return view,{key:_criterion(key,row) for key,row in candidates.items()},INSTRUCTIONS
