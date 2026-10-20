"""Read-only native director cards. Model wording + authoritative build status.

This module does not create goals, choose tactics or infer achieved experiences.
"""
import json
import time

BUILD_STATUS = {
    'queued_not_completed': '已提交 · 等待引擎', 'building': '正在搭建',
    'completed': '搭建已确认 · 体验待验证', 'confirmation_unknown': '等待搭建回执',
    'rejected': '搭建未通过', 'failed': '搭建失败',
}
TASKS = {'rescue': '营救队友', 'assault': '突破守军'}
SCENES = dict(north_hook='北侧迂回',south_hook='南侧迂回',split_lanes='两路接近',
              central_breach='中央突破',offset_pockets='交错掩护',defended_corner='侧角据点')
SUPPORT = dict(infantry='步兵',rocket_team='火箭兵',tank='坦克')


def choice_visual(selected, progress, state):
    trace=selected.get('choice_trace') or {}
    scene=trace.get('scene_shape') or {}
    basis=selected.get('experience_basis') or {}
    flow=basis.get('experience_flow') or {}
    grounding=selected.get('grounding') or {}
    cells=grounding.get('cells') or progress.get('cell_choices') or {}
    # Keep real choice IDs and offered alternatives. Schematics are labelled as
    # intent; neither candidate scores nor rejected-choice reasons are invented.
    options=[dict(id=k,label=SCENES.get(k,k),selected=k==scene.get('selected'))
             for k in scene.get('options',{})][:6]
    result=next((r for r in (state.get('world_growth') or {}).get('mission_results',[])
                 if selected.get('operation_id') and r.get('operation_id')==selected['operation_id']),None)
    feedback='等待本关战斗反馈'
    if selected.get('status') in ('rejected','failed'):feedback='方案未通过 · 等待调整'
    elif selected.get('status')!='completed':feedback='方案待引擎确认'
    elif result:
        feedback={'completed':'本关已完成 · 体验效果仍需复盘','failed':'本关未完成 · 需要复盘'}.get(result.get('status'),'任务结果待确认')
    if selected.get('status') not in ('rejected','failed') and grounding.get('route_separation') is False:
        feedback='主侧路重合 · 尚未形成分路'
    return dict(options=options,selected=scene.get('selected',''),
        task=TASKS.get((trace.get('mission_kind') or {}).get('selected'),'任务待定'),
        support=SUPPORT.get((trace.get('support_type') or {}).get('selected'),'支援待定'),
        basis_id=basis.get('report_id',''),
        goal=str((basis.get('next_goal') or {}).get('experience') or '首关按当前配置选择')[:100],
        why=str(flow.get('hypothesis') or basis.get('current_analysis') or '尚无上一关体验报告')[:120],
        beats=[str(b.get('goal',''))[:40] for b in flow.get('beats',[])[:3] if isinstance(b,dict)],
        cells=[dict(id=k,label=str((v.get('props') or [v.get('template') or v.get('card') or '已选'])[0])[:40])
               for k,v in cells.items()][:9],
        feedback=feedback,geometry_verified=selected.get('status')=='completed')


def director_card(director, state):
    if not isinstance(director, dict):return None
    report=director.get('experience') or {}
    summary=report.get('presentation') or {}
    goal=report.get('next_goal') or {}
    history=director.get('history') or []
    built=history[-1] if history else {}
    prepared=director.get('prepared') or {}
    status=director.get('status','')
    recovery=director.get('recovery') or {}
    active=status in ('jev_planning','jev_building','prepared','commit_retry')
    phase=({'jev_planning':'正在策划下一关', 'jev_building':'正在选择场景与路线',
            'prepared':'方案已备好', 'commit_retry':'等待重新提交'}.get(status)
           if active else BUILD_STATUS.get(built.get('status')))
    if director.get('error'):phase='生成遇到问题 · 查看依据'
    if recovery and status in ('generation_blocked','awaiting_preparation'):
        phase='生成已暂停 · 重复失败' if status=='generation_blocked' else '方案未通过 · 准备调整'
    selected=prepared if prepared else built
    progress=director.get('generation_progress') or {}
    if status=='jev_building' and progress.get('mission_kind'):selected=progress
    if status=='jev_planning':selected={}
    task=TASKS.get(selected.get('mission_kind'), '任务待选定')
    layout=selected.get('layout_brief') or {}
    detail=['【观察报告】', report.get('current_analysis','尚未收到体验分析报告。'),
            '【依据与限制】',report.get('assessment','等待足够的战斗样本。'),
            '【下一关目标（尚未验证）】',goal.get('experience','尚未提出'),
            '战术问题：'+goal.get('tactical_problem','尚未提出'),
            '场景变化：'+goal.get('layout_change','尚未提出'),
            '避免：'+goal.get('avoid','尚未提出'),
            '【实际生成记录】', '任务：'+task,
            '状态：'+(phase or '持续观察中'),
            '生成意图：'+str(selected.get('intent') or selected.get('reason') or '待选择'),
            '场景关系：'+str(layout.get('scene_intent') or '待选择'),
            '布局方向：'+str(layout.get('programme_intent') or '待选择'),
            '本次生成引用报告：'+str(selected.get('macro_call') or '未记录'),
            '当前展示报告：'+str(report.get('report_id') or '未收到'),
            '操作回执：'+str(built.get('operation_id') or '尚未提交'),
            '错误：'+str(director.get('error') or director.get('analysis_error') or '无'),
            '说明：搭建完成只确认关卡落地，是否带来预期体验仍需后续战况验证。']
    flow=report.get('experience_flow') or {}
    if recovery:
        detail += ['【生成受阻】',recovery.get('message',''),recovery.get('next_action','')]
    if flow:
        detail += ['【体验判断】',str(flow.get('hypothesis','')), '未知：'+str(flow.get('uncertainty','')),
            '执行问题：'+str(flow.get('execution_issue','')), '偏好证据：'+str(flow.get('preference','')),
            '【未来体验安排】', '\n'.join(str(b.get('goal',''))+'：'+str(b.get('change',''))+
                '；观察 '+str(b.get('expected',''))+'；调整条件 '+str(b.get('reconsider','')) for b in flow.get('beats',[])[:3]),
            '【上次安排复盘（模型判断）】',str(flow.get('review',''))]
    visual=choice_visual(selected,progress if active else {},state)
    if recovery and status in ('generation_blocked','awaiting_preparation'):
        visual.update(build_label='生成暂停' if status=='generation_blocked' else '方案未通过',
            feedback=recovery.get('message',''),geometry_verified=False)
    elif selected.get('status') in ('rejected','failed'):
        visual['build_label']='方案未通过'
    return dict(headline=summary.get('headline') or ('体验报告已更新' if report else '导演正在观察战斗'),
                evidence=summary.get('evidence',[])[:3],
                next_goal=summary.get('next_title') or ('已提出 · 查看依据' if goal else '等待战况'),
                phase=phase or '持续观察中',task=task,
                report_id=str(report.get('report_id') or ''),
                source='AI 对战观察' if report.get('source')=='bot_battle_observation' else '战况观察',
                details='\n\n'.join(str(x) for x in detail)[:7000],
                generation=dict(active=active or built.get('status') in ('queued_not_completed','building'),
                    attention=bool(director.get('error')),
                    visual=visual,
                    status=(phase+'\n'+recovery.get('next_action','')) if recovery and status in ('generation_blocked','awaiting_preparation') else phase or '等待下一次生成',task=task,
                    scene=str(layout.get('scene_intent') or '场景关系待选定')[:100],
                    selected_cells=progress.get('cells',0),
                    intent=str(selected.get('intent') or selected.get('reason') or '')[:180]),
                run_id=state.get('run_id',''))


class DirectorDisplay:
    """Send changed cards, and only mark delivered after a native receipt."""
    def __init__(self):
        self.delivered=None
        self.pending=None
        self.retry_at=0

    def tick(self, director, current, state, game):
        payload=director_card(director,current)
        if payload is None:return
        signature=json.dumps(payload,sort_keys=True,ensure_ascii=False)
        if self.pending:
            ident, sent_signature=self.pending
            with state.lock:receipt=state.results.get(ident)
            if receipt is None:return
            self.pending=None
            if receipt.get('accepted'):
                self.delivered=sent_signature
                game.record(dict(type='director-display-applied',receipt=receipt,card=json.loads(sent_signature)))
            else:self.retry_at=time.monotonic()+2
        if signature==self.delivered or time.monotonic()<self.retry_at:return
        code, receipt=state.submit(dict(action='sidebar',faction='green',run_id=current['run_id'],director=payload))
        if code==202:self.pending=(receipt['id'],signature)
        else:self.retry_at=time.monotonic()+2
