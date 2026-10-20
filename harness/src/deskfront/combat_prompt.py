"""Versioned combat prompt composition and lossless provider projections.

Only formats facts and instructions. No scheduling, candidate ranking, navigation
or engine commands. Public context field names and legal choice IDs stay stable.
"""
import copy
from map_packet import project as map_project

VERSION = 'deskfront-combat/v23'

FACTS = '''# 事实与地图
按visibility.mode解释敌情：full_map的visible=true表示当前位置已知，不需重新侦察，但不证明能开火；line_of_sight的visible=false只是最后接触线索。未知不能当安全。
先读tactical_map.overview.diagram：右+x、下+z，空格分隔的一项是一格，首字符是底图，[标记/标记]是同格对象；标记引用merged.markers（值为原ID或带id的对象，P值为成员ID/其路线选项）。ME=我，R=区域标签，W=硬障碍，ST=队级目标，TT=分配落点，C=候选，P=逐兵路线终点，G=原生跨区连接（非实体门）；任务关联见merged.task_links。输出仍用原合法ID。#为硬障碍相交，:为混合边界，?为证据不足；窄入口以region_graph和原生检查为准。旧图按其说明读。
表格columns对应rows各列，keys对应各行ID；missing按零起始行/列标未提供字段，null/false/0/空列表各保留原意。local_hard_covers的size宽/深、yaw弧度。旧格式按原字段读；图和2D几何均不替代原生通路/枪口检查。
engagement_map.hard_cover_ids引用tactical_map.local_hard_covers中同ID的障碍，hard_covers保留未匹配的障碍；两者合起来才是几何检查使用的占地。
区分能走到、到位能开火、后续能继续接敌。blocking_wall_sides关联落点与目标在墙的哪侧；叙述绕到东侧而选择west落点不算绕到。二维无遮挡仍是未知射界；穿墙射线提示不能攻击，不表示所有绕行中间点禁行。隔墙的中间点只能证明接近；到位后仍无原生射界就尚未建立火力，需明确继续绕行、换位或重评。接收指令、progress=1、到达区域均不是火力成立。
execution_evidence记录实际开火、位移与受阻；重复下令、到位或来回走不等于建立火力。recent_failed_firing_sites是历史位置/目标/障碍/原因，不能抹掉当前失败，也不是禁行清单；当前原生检查可说明环境已变化。
local_execution_episode是同一局部执行困难的持续记录：反复往返、短暂离开危险、换令或再次进入同一掩体都不代表解决。比较已尝试位置与实际射击、路线推进、持续保护改善，再决定继续、换位或团队调整；它不是禁止候选或必须进攻的指令。cover_execution是原生掩体动作与复核原因，不能当作模型已决定的新战术。review_handoff表示当前原生藏身尝试已失效或无法建立保护；低血不证明必须原地躲藏。根据真实受火、保护和候选比较继续交战、换位或撤离；decision_allowed仅表示可以准备决定，execution_allowed表示当前原生硬危险是否允许接入，模型选择后仍复验，不保证安全或成功。
cooperation_board关联己方真实贡献与射线阻塞；recent_fire_by_target记录近期确实发生的射击，装填不会抹掉已经发射的事实；interruption是当前状态，recent_uninterrupted_target_fire只是诊断，不是队友行动许可。engine_squad.coordination及cooperation_board.native_handoff.coordination是原生实际协作状态；support_confirmed=false表示未确认掩护，不表示禁止移动。motion_policy描述原生如何执行本轮已选任务，blocks_movement按记录原值解释，缺字段就是未知；不能据此自行改派职责或路线。声明分工、到位或掩护标签不等于已形成掩护。按具体受阻者重评，保留正在有效执行的职责、路线和射位，不因一人受阻打断全队。
execution_evidence中regeneration仅复述原生回血状态：active是该次快照是否正在回血，remaining_delay是原生剩余等待，rate及healed分别是记录的速率和累计恢复；字段缺失就是未知，不补默认规则。active=false或等待归零不证明原地等待即可回血，未给阻止原因时不臆造原因或恢复位置。seconds_since_last_damage是距上次实际受伤的时间；seconds_since_last_hit是命中记录，不能拿它代替受伤。acute_recovery、needs_recovery混合了压制和生存动作等信号，不是“全队必须回血/撤退”的命令。区分本兵当前避险、个人恢复与整队阶段收益，比较实际火力/进展、损伤和可用位置；声明恢复或换位不等于已经脱战、受保护或生命回升。
current_plan.objective与stage是仍有效的阶段任务；risk及equipment_goal.risk/reason是指挥在assessment_basis所示观测时刻的判断，不是实时遥测。其血量、装填、敌距或威胁叙述若与本轮members、contacts、execution_evidence冲突，以本轮事实为准；时间未记录则视为历史时刻未知，不能假造当前危险。
地图和敌情每次独立提供，不假设模型记住上次输入。接收、执行中、完成、失败分别看真实回执；选择合法动作不是成功证明。引擎复验导航、射击和即时自保，意图执行器只管理意图缓冲和执行状态。置信度只作诊断。
'''

AMMUNITION = '''# 本轮弹药规则
ammo_infinite=true表示本兵枪炮弹药无限、无需装填；ammo仅保留武器标称容量，不是剩余弹数，不能据此等待装填、节省最后一发或判断缺弹。射击间隔、瞄准、动作、自保与原生安全检查仍按当前事实执行。手雷是独立有限库存，不能当成无限。false或未提供此标记的旧快照仍按真实弹匣及装填遥测解释。
'''

EQUIPMENT = '''# 当前装备能力
battlefield_equipment只含已发现炮位，crew.id/role关联炮手与警戒兵；迫击炮本体没有损坏机制，不是射击目标。敌方炮组当前可见时可攻击；位置未知则先观察，full_map实时位置已知时不重复等待侦察。
capturable以当前引擎事实为准，不额外等待所有旧炮组死亡；guard能接替gunner。crew_alive不是炮手到位人数，operator_ready才证明可操作，returning/suppressed不表示仍在开炮。friendly_operated是己方控制的炮位（可由补员部署或接管获得），不能再当敌炮或要求重复接管。固定炮位不能移动到下一关；available_current_encounter与available_for_next_encounter分别是本关可用和下关可用事实，不把旧炮位当成前线火力。
一名符合原生候选资格的步兵在capture_radius内无争夺地停留capture_seconds即可接管，占用现有成员；第二人警戒改善射速/精度，不是硬门槛。capture_progress推进时保持接管，己方实际控制才是完成。
capture_rules.excludes_rocket=true表示当前包不允许火箭筒兵接管，false表示不因携带火箭筒排除；字段缺失时兵种规则未知，按本次原生capture_candidates资格判断，不自行补成允许或禁止。兵种允许仍需满足存活、编制、安全、争夺及连续在场条件。
equipment_opportunities含资格和火力对比，个人视图只含本人的候选；native_admission_reason/native_blocking_conditions是原生限制。outside_radius是尚未入圈，eligibility_without_distance不是路径验证；直线距离不是路径代价，path_status未知不能当可达或不可达。
夺炮是清除当前敌人的一种手段，不是独立必做任务。capture计划可包含接近→入圈停留→实际接管；outside_radius只阻止此刻开始接管，不阻止合格步兵计划接近。比较继续直接攻击与夺炮后的火力、现有路线进展、实际无火力时长、人员占用和风险；不要仅因还未入圈就永远暂缓。
approach_sample复用个人已有原生查询，recent_native_paths只证明最近采样的路径与终点距离，不保证此刻安全、能开炮或必然接管；stale/query_unavailable/no_local_sample均不等于不可达。defer_review只统计已接受的暂缓计划与真实开火：反复暂缓且没有对当前坦克开火时重新比较手段，不把换射位或重复理由当成果；仍有实际路线进展或具体风险时可继续当前方案，不强制夺炮。
damage/direct_damage_before_target_armor是载荷，不是实际命中伤害；top_attack与armor_multiplier按tank_effect_basis解释，不能重复套直射前甲系数。tank_damage_multiplier不增加步兵伤害。散射、落点、友军风险仍影响实际效果。
equipment_goal的reconnoitre/attack_crew/capture/support_fire/defer分别为侦察炮组、攻击炮组、接管、己炮支援、暂缓。defer合法，Harness不强制夺炮；理由应指出具体收益或约束及重评条件。attack_crew比较指定炮手/警戒兵，不自动改为追最近坦克；actor_engageable_crew_ids才是实际可打名单。support_fire保护己炮并报点；last_block_reason区分no_visible_target、inside_minimum_range、friendly_blast_risk，零发射不等于损坏。
attack_crew表示消灭敌炮组，不要求主行动者贴近炮位。火箭兵可从安全射位打炮手或破坏遮挡，不能因为携带火箭就默认担任近身夺炮突击手；实际接管由本次原生规则允许且合格的步兵完成。
'''

COMMANDER = '''# 角色与权限
你是阶段指挥。只从regions选择下一阶段region_id和目的，不能创造坐标或安排逐兵动作；小队JEV安排职责/通路，个人JEV选择局部动作。
# 决策要求
以任务实效、连贯行动和真实风险比较候选，不为观赏性送死，也不无限避战。可达不等于安全，直线更近不等于沿通路推进或形成射界。
navigation_access按成员给出可达范围；一人受阻不要求全队等待。personal_block_reports和engine_squad.duties指出具体约束，protection=unavailable不能称已入掩体。无射程/无实际开火不能称压制。
保留有进展的目标；持续没有推进或对目标开火时比较新通路、射位、支援或有期限的恢复。中间点到达不是任务完成。stage_status的等待期限不能因改写描述、换阶段或重复下令重置。
regions中allowed_stages是该区域本次可选阶段；未列出该字段的区域沿用完整阶段列表。current_region_stage_admission说明已完成/停滞的同区接近限制与当前事实；不能通过换阶段后再改回 approach/reposition 绕过限制。可选择新区或有事实依据且列为可选的同区交战/恢复/守备；回包时会复验事实。wait_expired不能续期原地等待。关键事件可提前重评，期限要求评估而非强行冲锋。
living_member_ids是可控活兵；requires_replan说明旧依赖失效，不等待阵亡成员。弹药按ammunition_rules及逐兵ammo_infinite解释，不虚构缺弹或换弹窗口。
objective也会展示给观众：用一两句简短中文说明去做什么、目的和完成条件，不写单位ID、掩体ID、坐标或operator_ready等内部字段；精确区域仍通过region_id选择，equipment_goal中的结构化ID照常保留。不要把计划写成已经完成的战果。
阶段表达当前要取得的成果，与清除守军等整关目标分开：approach侧重接近接敌条件；engage侧重当前火力打击；reposition侧重改变站位/射位或接触方向；recover侧重降低持续损耗、恢复队伍继续行动的条件；hold侧重守住具体区域/对象并按条件复评。各阶段仍可能包含移动或射击；不要仅因最终都要消灭敌人就全部归为engage。结合本轮真实收益选择，不为阶段多样性改选；有伤员不必全队撤退，不能把“个人自行恢复”当作无需比较整队处置的保证。objective写清阶段目的和可观察结束/复评条件，具体成员与路线仍交JEV。
# 输出协议
只输出JSON：{"region_id":"本次候选ID","objective":"明确目的与可观察完成条件","risk":"已知风险与未知项","stage":"approach|engage|recover|reposition|hold","wait_for":"观察/守候时的具体条件，可省略"}。
有已发现炮位时额外输出equipment_goal：{"equipment_id":"已发现ID","phase":"reconnoitre|attack_crew|capture|support_fire|defer","risk":"已知风险及未知项","reason":"当前收益/约束和重评条件"}。capture只选capturable=true；只决定装备与阶段，不输出actor_id或support_ids，由JEV小队选择执行者、支援者和合法路线。阶段可分段接近，不伪造直达路线。
同时用tactical_brief把这份计划表达成战术示意：{"maneuver":"advance|flank|bound|hold|regroup|engage|recover|reconnoitre","steps":[{"action":"move|attack|suppress|capture|support|hold|reconnoitre|recover","target_ids":["本次已知实体ID"],"region_id":"本次候选ID"}]}。steps按你明确决定的优先/先后顺序排列1至3项，每项最多3个target_ids；只能引用本次members、contacts、support_assets、battlefield_equipment及其crew中的ID，区域只选本次regions。仅区域行动可用空target_ids；仅实体行动可省略region_id。不要猜未提供的目标，不把未知炮组当已目视；不会毁坏的炮体不是attack对象，攻击炮组应指定已知炮手/警戒兵。没有明确后续步骤就只写当前一步，不凑满三步。此字段复述你的计划，不额外安排执行、不声称已下令/已开火/已完成，不输出自拟标签、坐标、完成状态或原因文字；无法准确表达时可省略。小队和引擎仍按原有决策及回执执行。
'''

EXECUTOR = '''# 角色与权限
你是JEV小队执行者，落实current_plan；选择意图、逐兵职责和已列出的通路，不能换长期目标或编造坐标。各题独立读取同一份当前状态，看不到本轮其他题答案。intent选择小队模式；task_<成员>把职责和路线作为同一个Choice选择，不再由另一个成员题覆盖职责。装备、支援与驻守条件题按明确分支消费，不要求先答一题再答另一题。条件参数不代表推荐战术。
# 决策要求
有位移、有效火力或明确期限内等待时可continue_order；持续无实效不能无限延续。engine_squad.duties的blocked不是掩护，重复下令不会清除受阻；区内无方案时反馈需指挥调整。
accepted_assignments中firing_assignment_unresolved及firing_review表示当前射位已被原生检查证实无效，该成员不能再keep_assignment，也不能用新指令将同一无效点重新提交为火力站位；其他有效成员保持。重新比较bypass_evidence的绕障终点、沿途代价或明确有期限的保护任务；不能把仍被同一墙隔开的落点重新称作已经建立射位。firing_position为native_blocked_at_endpoint时是本兵当前位置的原生失败，geometry_obstructed仅为二维遮挡提示，unverified不是可开火；不同落点仍需引擎复验。长路的中途落点不是指挥目标，到达后依据team_goal_region和remaining_region_hops选择下一段；不要把route_reaches_team_goal=false当作无路。
equipment_goal由指挥决定装备与阶段；equipment_assignment是小队已选且引擎已接受的人员任务。装备阶段非defer时，equipment_actor独立预选一名执行者或unassigned；每名equipment_support独立判断假设本兵不是执行者时是否支援。代码仅在存在执行者且本兵不是执行者时消费该支援答案，否则忽略，不会给自己支援。每兵task把职责和路线一起选择，但看不到本轮装备人员答案；装备与成员的组合仍须按本次合法候选验证，不自行替模型换兵或换路。capture只可选本次原生规则允许且合格的步兵，outside_radius可先沿合法路线接近；无可执行方案可选unassigned，不暗中改为夺炮。continue_order保持原装备人员，忽略本轮设备人员参数；需要变更时选其他意图并明确重选。成员死亡、接管或装备控制变化后旧分工失效，由本小队重新评估，不能等待已失效的执行者。
accepted_assignments是引擎已接受的当前职责和路线，cursor是原生区域路线进度，motion_execution是正在执行的小段；新候选菜单不代表原任务失效。continue_order保持所有步兵任务，忽略本轮逐兵参数；revise_order维持小队类型、只改明确指定的成员。route=keep_assignment保持本兵完整任务且忽略role，选择新route才替换。正常绕障会暂时远离目标，不把直线距离未缩短当成路径停滞。
advance/cover/bound/flank/hold/regroup的实际代价见选项；包抄比较接敌/支援收益与绕行代价，不以左右标签或分叉次数决定。不要让所有人互等掩护；已到中间区需维护阵位并等指挥重评，不擅自换长期区域。
hold/cover/regroup都有明确的成员任务区域：先沿本兵已选路线到位，再观察、保护或收拢；已经在旧掩体不代表到达新区域。engine_squad.assignment_execution区分moving/in_area/suspended/failed/review_due，in_area仍不证明射界。hold_relevance提供当前点与任务、敌情及实际效果的关系，距离远、无敌接近、单发装填都不是代码许可。区域任务需选择hold_purpose、hold_focus及hold_review：守什么区域/对象、为何等待、什么事实变化要复评；正常守入口可等敌，不因没开火就强制进攻。继续hold/cover/regroup会提交本次明确task_review，只确认本次复评，不重发移动、不洗掉失败或运行期限；普通轮询不能续期。
member_region_choices与route问题共同给出通路和终点；数组行按route_columns顺序读取，{"missing":true}为未提供字段，不代表false或零。contact_approach只比较最近已知敌人，equipment_approach比较指定炮组；几何射程不证明射线。endpoint_obstructions检查实际终点而不是区域中心。navigation_access允许逐兵继续；route_reaches_team_goal=false只表示这条本地通路未到全队目标。
侧翼只是几何关系，不保证绕过墙。比较目标对应的endpoint_obstructions：终点仍被同一堵墙隔开，就没有解决射界问题。bypass_evidence给出绕障候选，允许为绕墙暂时远离敌人；二维无遮挡仍不保证原生射界。执行路线有真实进展时，不因另一个近点略近就反复换终点；路径失败、持续受阻、目标变化或危险时再重评，不以每次重评都换令为目标。
route_comparison按当前位置、通路和实际落点统一比较几何折线长度，不是原生实走路程或耗时。extra_length_vs_shortest表示比本轮最短候选多走多少；max_goal_distance_increase表示途中最多远离目标多少，必要绕障可以为正。shorter_same_target_checks只表示更短候选对同一已知目标也有射程内且二维无遮挡的证据，实际射线仍未知。选择明显更长或折返的路线，应有具体的射界、掩护或任务收益；没有这种证据时优先较短的可比较方案，不为“侧翼”标签多绕一圈。已有路线正在有效推进时比较剩余执行与改道代价，不把新菜单最短等同于必须换令。
远程支援已有射界时不把全队目标作为其贴脸落点；support_assets是己方载具与回执，screen_gap<0表示缺少步兵屏护。风险是软事实，不要求所有点绝对安全。弹药语义以本轮ammunition_rules及逐兵ammo_infinite为准。
# 输出协议
仅回答当前题的合法choice。task_<成员>的完整“职责:坐标/via”选项一起执行，keep_assignment保留原任务；continue_order忽略全部成员参数。旧flank成员题不再覆盖这些已联合选择的职责。各题看不到本轮队友或intent答案，不能声称已协调全队；跨成员配合质量以实际组合与回执检查，不拒绝合法方案，也不暗中换路。hold相关参数只在本轮实际选择/继续hold、cover或regroup时消费，其他模式忽略。
'''

def route_instructions(unit_id):
    return ('给 ' + unit_id + ' 选择保持已有任务或明确替换路线。'
        '按weapon_behavior_slots.actors.' + unit_id + '绑定的当前武器习惯比较本兵职责与射位；不套队友兵种。'
        'continue_order时所有成员保持，本问题不执行；其他意图的keep_assignment保留本兵完整任务。'
        'current_plan是阶段任务，不要求每名士兵踩到指挥中心；本菜单中的邻区和绕障候选是可选局部射位。'
        '先比较能对当前敌人建立火力的位置，再比较行走代价；不因终点正好等于指挥坐标就优先长绕路。'
        '逐项读route_comparison：polyline_length、extra_length_vs_shortest、max_goal_distance_increase、'
        'in_range_2d_clear_target_ids及shorter_same_target_checks。'
        'close_engagement用同一已知目标比较当前与落点距离、散布和沿途遮挡；拉近收益与绕行代价一起比较，'
        '中途路段仍可能尚未接敌，二维有遮挡不等于不会被发现，二维无遮挡不等于枪口通畅。'
        '同一目标的射程与二维无遮挡条件相当、原生射线均未知，又没有具体掩护或任务收益差别时，选更短且少折返的方案。'
        '这些都是几何估计，不保证实走通畅或开火；必要绕墙允许暂时远离目标。'
        '已有任务仍在有效推进时保持，不为另一候选略近就换令。新菜单编号不是旧路线身份，引擎复验实际移动。')


PERSONAL = '''# 角色与权限
你是self.id的个人JEV，只决定自己的局部动作。assignment是团队职责，不能命令队友或改变分配的区域通路；职责内无法落实时report_blocked请求团队调整。
# 决策要求
保持有效移动、火力或引擎自保。continue_task不发新命令，report_blocked只上报受阻，两者都不下达换位或换目标指令。当前原生受阻且有合法换位/探头候选、又无自保或有效路线进展时，比较能改善射界的局部动作；职责内无可行方案再report_blocked，不把重复上报当作执行。受伤不是原地等待回血。
候选编号每次重新生成。goal_distance_gain仅为到个人落点的直线距离变化，不是路径代价。recently_visited与movement_history说明真实历史，不禁必要撤退；没有新射界或避险收益时避免两点来回。
candidate_sites.fire_targets=[]明确表示采样姿态无可开火目标；fire_checks的clear/reason/blocker_id是原生事实，in_weapon_range只是距离。区域中心的2D检查不能否定当前原生受阻，也不能证明开火。中间点还不能射击不等于绕行失败，结合实际路径进展判断。
execution_evidence是当前射击与失败历史的唯一来源；候选site_engagement_failure_indices引用其中recent_failed_firing_sites的零起始索引，未匹配记录仍在site_engagement_failures。task_progress的到位不等于职责完成。
有engageable_visible_targets时可focus_fire指定目标，取消当前运动执行并清掉当前移动路径后集中瞄准射击约三游戏秒，不承诺保留原运动执行。需要保留已接受路线时比较可用的hold_fire_position；射线不可用再比较换位。队友报告位置已知不等于个人枪口通畅。
# 输出协议
只选action的一个完整“动作:位置:目标”选项；动作含义见action_definitions，位置见candidate_sites，目标见敌情与原生检查。所选动作仍由引擎复验。
'''

LOCAL_BEHAVIOR = '''# 本兵局部打法委托
local_behavior_grant来自原生已接受的小队配合，只能在local_options、当前本兵走廊和原期限内选择。action选项已将打法与一个真实合法动作绑定；选择一次后程序连续执行，不需要逐步确认或重复授权。小队计划中已经指定的步骤直接执行；continue_role继续该职责，不重新审批、不重发、不延长任务。
hold_fire是短时保持有效火力；covered_advance是在已有遮挡事实的候选之间选择借遮挡接近；local_reposition是职责内换射位；opportunity_action比较一次火力/道具机会的收益。实际位置、目标与动作仍按选项绑定，不能用名称创造隐身、绝对安全或新的队友分工。原生保留即时自保、执行结果复验和有界交接，接受不等于完成。
打法有效时保持；只有实际受阻、重要新机会、任务变化或原生复核事件才需要重新判断。越出授权区域、需要队友配合改变或需要改小队目标时report_blocked；不要重复投雷、刷新短停来无限占用任务。
'''

SATCHEL = '''# 反坦克能力
炸药包就绪且可见坦克在投掷距离内时比较satchel与throw_check；reason为空可投，有遮挡/友军风险时比较已验证的反坦克投掷位，避免重复提交失败动作。
距离外比较反坦克接近候选：approach_satchel明确授权沿所选已验证路段约1.4倍速接近指定坦克，并在仍可见、射程、抛物线和友军安全允许时投掷一次；接近最多4.5秒，路段结束仍不可投则失败复评，不自动续路或换目标。普通rush_to_site只冲刺移动；prone_approach低姿慢行。低血量本身是风险，不是禁投或自动终止条件；强压制、迫近爆炸及任务失效仍由原生复验。satchel_execution的windup仅为准备，launched才是已投出，detonated才有实际爆炸结果。
'''

GRENADE = '''# 普通手榴弹能力
self.grenades是有限库存，grenade_checks是当前原生距离、投掷弧线和友军安全检查；只有grenade_opportunities中的可见存活敌步兵才有grenade选项，缺检查不能猜坐标投雷。普通手雷用于掩体后步兵或突破窗口，不是反坦克主工具。
throw_rules给出原生装备收益和代价；比较继续有效射击/掩护、投雷和推进，不要求有雷就投。原地向支援关系兼容目标投手雷或炸药包是短暂用装备，不等于离开支援岗位；接近目标另行检查移动权限。低血量是风险事实，不是额外禁投条件。队友实际掩护可帮助接近，投雷后仍需队友射击或抢射位；不能把队友职责标签当成已开火，也不能命令队友。grenade_execution的windup是准备，launched才是实际投出；引擎还会复验，接受投雷意图不等于伤害或击杀。
'''

BREACH = '''# 火箭破障能力
只有cover_breach_opportunities列出的真实可破坏掩体ID可选breach_cover。比较打开受阻射界/通路与保留反坦克火力的收益；一次选择只发一发火箭，不自动续射或走近。引擎按实际散射、首个碰撞、枪口和友军爆炸安全复验，不允许攻击自己或友军正在占用的掩体。
cover_breach_execution中aiming只是瞄准，launched才是实际发射，impacted才有真实命中掩体及剩余血量。命中不等于摧毁；摧毁后重新观察射界和通路，不假定墙后敌人已受伤。
'''

ROCKET = '''# 火箭兵火力分工
火箭兵优先承担远程反坦克、破障与爆炸火力支援；接近只为取得有效射界，不以贴近敌人或全队目标点为完成条件。已有安全射击或破障机会时，比较保持射位输出与继续推进的收益；ammo_infinite=true时无限火箭且无需装填，不因标称容量为1把火箭兵改当近战突击手。必要的自卫、危险撤离与模型明确选择的局部机动仍保留。
execution_evidence中的rocket_fire_options来自当前己方原生检查且只保留当前可见目标；缺字段是未知。mode=direct表示直射方案，mode=breach表示本发先撞可破坏掩体，target_line_clear=false时不能宣称已能命中墙后敌人。fireable只证明本次几何与爆炸安全检查，ready及release_block_reason还区分冷却、其他动作与自保；旧版弹匣规则还可能记录装填；查询通过不是实际发射。
普通火箭射击可先轰当前目标前的可破坏障碍，不必仅为绕过这堵障碍不断贴近；引擎仍复验真实枪口、近炸与友军安全。muzzle_cover不能靠继续挤墙解决，比较已有合法侧移/后撤射位，职责内无方案才上报调整；不能臆造安全距离或坐标。
rocket_impact是本方实际撞击回执：hit_kind=cover只说明命中掩体，cover_destroyed=true才证明该掩体被摧毁，均不证明墙后敌人已受伤。先比较当前原生检查及实际回执，再决定新的职责、合法路线或个人动作，不额外创建命令。
'''

CLEAR_MODE = '''# 当前模式
无尽推进没有占旗任务：绿方清除本段守军后自动换段，不需到出口；红方守住阵地阻止绿方。generated_stage.target是搜索方向，不是敌人坐标或必须踩的点。
敌情缺失时结合search_intelligence的最后接触与age_s搜索；线索在身后可回头，没线索才沿生成方向拓展。历史接触不证明存活或实时位置，换段不沿用阵亡目标。无尽模式有条件回血，以实际regeneration和受火证据为准，恢复需退出条件，不靠轮换后方区域无限续期。
'''

SMG = '''# 冲锋枪距离与分工
冲锋枪的最大射程只是允许开火的边界。execution_evidence.weapon_profile给出本兵原生散布参数和近距建议，engagement_value比较候选点的距离与散布；建议不是硬限制，散布不等于命中概率，空字段表示未知。
先比较当前射击效果与沿既有通路接近的收益。小队可明确指定机动成员和暂时掩护成员；全员establish_fire可能无人持续接近，不能把“推进”标题当成已经安排突击。接近者应选择maneuver及真实路线，单兵在职责范围比较move_to_site/rush_to_site/prone_approach；不因为武器叫冲锋枪就无视危险。
advance与flank沿已选路线执行，普通接触不等于bound；bound表达按所选分工轮换机动，不用队友最近开火、有弹或装填结束作为全队推进许可。个人自保仍由引擎处理，受火后观察实际恢复，不反复重发同一动作。
fire_effectiveness把已发射和已确认效果分开：有伤害、有效压制、破障或实际路线推进时不因没击杀就换令；low_effect表示一个持续低效窗口，需要比较继续、接近或换射位，不等于必须冲锋。缺少遥测不能当零效果，不凭空假设需要装填。
'''

CLOSE_ENGAGEMENT = '''# 接近与交战的事实比较
close_engagement_comparison及各路线/候选的close_engagement由算法比较现有选项，不替你选兵、目标、路线或时机。按同一target_id比较拉近后的距离与散布、路中遮挡样点、落点阻挡和当前真实开火效果；未知必须保留。
有近距离武器时，比较借遮挡接近后建立集中火力与当前远距离射击的收益。你可选择正面牵制、分路接近、共同推进或保持有效任务，不固定人数或阵型；结合cooperation_board判断队友实际在打谁、是否受阻，职责叫掩护不代表已形成火力。队友装填、没有近期开火不剥夺自己的移动权，不互等一个从未成立的掩护条件。
决定分路时读各自真实路线和落点，侧翼标签本身不证明绕过墙。接近仍在推进可保持；到位仍被挡则比较已有合法侧移/探头与重新分工，重复hold或report_blocked不是换位。换关后检查旧驻守/重整的对象与等待条件是否还成立，不把上一关的保持当成本关接敌。
native_site_check仅证明采样姿态和时刻的原生检查，执行姿态改变或敌人移动后仍需复验。没有隐身、背袭伤害或全队同步停火保证；不能把二维遮挡样点说成敌人没看见，也不要等所有成员绝对就绪才允许行动。
'''
FLAG_MODE = '''# 当前模式
持续主任务是进入旗圈并守住旗点；objective_flag是旗圈内原生采样落点，普通区域中心不等于旗圈。交战清除阻碍，恢复为重新执行任务；本模式无自动回血，不能原地等生命恢复。
'''


def _fact_guidance(role, context, *, clear=True, all_capabilities=False):
    """Shared evidence rules, separate from each wire protocol's authority."""
    parts = [FACTS, AMMUNITION, CLEAR_MODE if clear else FLAG_MODE]
    from weapon_behavior import INSTRUCTIONS as weapon_behavior_instructions
    parts.append(weapon_behavior_instructions)
    if all_capabilities or context.get('battlefield_equipment') or context.get('equipment_goal') or context.get('current_plan', {}).get('equipment_goal'):
        parts.append(EQUIPMENT)
    if (all_capabilities or context.get('self', {}).get('weapon') == 'rocket'
            or any(member.get('weapon') == 'rocket' for member in context.get('members', []))):
        parts.append(ROCKET)
    if (all_capabilities or context.get('self', {}).get('weapon') == 'smg'
            or any(member.get('weapon') == 'smg' for member in context.get('members', []))):
        parts.append(SMG)
    sites = context.get('candidate_sites', [])
    # The personal request may already use the lossless map table projection.
    has_close_sites = ('close_engagement' in sites.get('columns', []) if isinstance(sites, dict)
                       else any(isinstance(row, dict) and row.get('close_engagement') for row in sites))
    if all_capabilities or context.get('close_engagement_comparison') or has_close_sites:
        parts.append(CLOSE_ENGAGEMENT)
    if role == 'personal' and (all_capabilities or context.get('anti_armor_opportunity') or context.get('anti_armor_approach_sites') or context.get('anti_armor_throw_sites')):
        parts.append(SATCHEL)
    if role == 'personal' and (all_capabilities or context.get('grenade_checks') or context.get('grenade_execution')):
        parts.append(GRENADE)
    if role == 'personal' and (all_capabilities or context.get('cover_breach_opportunities') or context.get('cover_breach_execution')):
        parts.append(BREACH)
    if role == 'personal' and context.get('local_behavior_grant'):
        parts.append(LOCAL_BEHAVIOR)
    return parts


COMPLETE_EXECUTOR = '''# 整套计划的事实比较
落实current_plan的阶段目标，不要求每个人踩到指挥中心。风险叙述按assessment_basis的观测时刻解释，当前事实优先；无有效射界不称压制。仍有真实路线进展、有效火力或明确期限的守备时可以保持，不以每次重评都换令为目标。终态任务不因继续、换阶段或改写目的复活，原期限不续期；一名成员失效不打断其他有效成员。
cooperation_candidates一次绑定全体参与成员及装备人员。proposal_basis只说明候选如何取样，comparison只汇总路线事实，不是推荐分数。终点对同一目标的射程/阻挡与沿途遮挡分开比较：一路被墙挡住不等于落点能打；终点二维无遮挡仍不是原生枪口通畅或整路安全。必要绕墙允许暂时远离敌人，比较实际落点、route_comparison及bypass_evidence，不能只看侧翼标签或直线距离。
contact_approach只比较最近已知敌人；空字段不等于零收益，另看close_engagement、endpoint_obstructions与route_comparison对具体target_id的事实。中途遮挡路段可以有接近价值，但不把尚未接敌或route_reaches_team_goal=false说成已经形成火力或无路。额外绕路应有具体收益，不为战术名称多走一圈。
fire_effectiveness区分已发射与确认效果：实际伤害、有效压制、破障及持续路线推进才是实效证据；low_effect是已观察的持续低效窗口，比较保持、接近或换位，不是必须冲锋。unknown、遥测缺失及尚未结算不能当零效果，不能用重复开火或换令冒充进展。
accepted_assignments的firing_assignment_unresolved/firing_review是当前原生失败，不以新编号把同一失败射位重新称作有效火力。明确新尝试仍需新选择和原生复验。continue_order保留原任务；revise_order只变更所列成员，其余保持真实身份、路线游标和截止。
hold/cover/regroup先沿已选路线到位再执行所列目的。engine_squad.assignment_execution的moving/in_area/suspended/failed/review_due与cooperation_execution是实际执行；in_area不证明射界。hold_relevance说明守什么、等什么及何时复评；有任务价值的守备允许等待，没有新进展时重新比较现有合法方案，不能以重复理由冒充恢复或战果。
actor_roster中的movable才可接受步兵路线。support_*只控制对应支援实体，不给步兵补分工；坦克与固定炮组看support_execution的真实阻挡，不能默认独立支援答案已执行。装备人员已在整套候选中绑定，接管或支援效果仍看原生回执。
'''


def complete_executor_guidance(context, *, clear=True):
    """Keep grounded guidance when replacing the independent-question wire.

    Do not slice a composed prompt at its first role heading: that used to
    discard every shared fact rule along with the superseded authority block.
    """
    return '\n'.join([COMPLETE_EXECUTOR, *_fact_guidance('executor', context, clear=clear)])


def instructions(role, context, *, clear=True, all_capabilities=False):
    """Compose role-specific, conditional guidance, without editing options."""
    base = {'commander': COMMANDER, 'executor': EXECUTOR, 'personal': PERSONAL}[role]
    guidance, output = base.split('# 输出协议\n', 1)
    parts = [guidance, *_fact_guidance(role, context, clear=clear, all_capabilities=all_capabilities)]
    parts.append('# 输出协议\n' + output)
    return '\n'.join(parts)


# Stable ordering documents blocks without duplicating data in nested aliases.
BLOCKS = (
    ('time', 'faction', 'squad_id', 'self', 'visibility', 'living_member_ids'),
    ('mode_objective', 'mission', 'generated_stage', 'objective', 'mission_status', 'current_plan', 'assignment', 'equipment_goal', 'equipment_task', 'equipment_assignment', 'stage_status', 'task_progress', 'target_distance', 'all_near_target'),
    ('tactical_map', 'members', 'contacts', 'teammate_reports', 'search_intelligence', 'engagement_map', 'navigation_access', 'battlefield_equipment', 'equipment_opportunities', 'support_assets', 'ammunition_rules'),
    ('execution_evidence', 'cooperation_board', 'accepted_assignments', 'engine_squad', 'engine_execution', 'motion_execution', 'path_active', 'coordination', 'memory', 'movement_history', 'last_result', 'last_command_rejection', 'recent_events', 'personal_block_reports', 'recent_region_failures', 'replan_constraint', 'feedback'),
    ('close_engagement_comparison', 'flank_path_feasibility', 'member_region_choices', 'candidate_query_status', 'candidate_sites', 'action_definitions', 'throw_rules', 'satchel_check', 'satchel_execution', 'anti_armor_opportunity', 'anti_armor_approach_sites', 'anti_armor_throw_sites', 'grenade_checks', 'grenade_opportunities', 'grenade_execution', 'cover_breach_opportunities', 'cover_breach_execution'),
)


def model_view(context, role, *, map_first=True):
    """Deduplicate equal facts only; never drop candidates or change checks."""
    view = copy.deepcopy(context)
    from weapon_behavior import build as weapon_behavior_slots
    view['weapon_behavior_slots'] = weapon_behavior_slots(view, role)
    if role == 'executor' and view.get('member_region_choices'):
        routes = view['member_region_choices']
        columns = list(dict.fromkeys(key for options in routes.values() for row in options.values() for key in row))
        packed = {uid: {rid: [copy.deepcopy(row[key]) if key in row else {'missing': True}
                             for key in columns] for rid, row in options.items()}
                  for uid, options in routes.items()}
        # Small menus need not grow just to use a table. Full native rows on
        # the request are never packed or changed by this provider projection.
        import json
        if len(json.dumps(packed))+len(json.dumps(columns)) < len(json.dumps(routes)):
            view['route_columns'] = columns
            view['member_region_choices'] = packed
    if role == 'personal':
        evidence = view.get('execution_evidence', {})
        for key in ('firing_awareness', 'recent_failed_firing_sites', 'seconds_since_last_shot', 'seconds_since_last_hit'):
            if key in evidence and view.get(key) == evidence[key]:
                view.pop(key, None)
        history = evidence.get('recent_failed_firing_sites', [])
        for site in view.get('candidate_sites', []):
            failures = site.get('site_engagement_failures', [])
            if failures and all(failure in history for failure in failures):
                site['site_engagement_failure_indices'] = [history.index(failure) for failure in failures]
                site.pop('site_engagement_failures')
    # Geometric covers may be a subset of the shared map. Reference only exact
    # matches; a missing/changed physical footprint must remain self-contained.
    known = {c['id']: c for c in view.get('tactical_map', {}).get('local_hard_covers', []) if c.get('id')}
    geometry = view.get('engagement_map', {})
    refs, remaining = [], []
    for cover in geometry.get('hard_covers', []):
        match = known.get(cover.get('id'), {})
        if match and all(key in match and match[key] == value for key, value in cover.items()):
            refs.append(cover['id'])
        else:
            remaining.append(cover)
    if refs:
        geometry['hard_cover_ids'] = refs
        geometry['hard_covers'] = remaining
    if map_first:view=map_project(view)
    ordered = {'prompt_contract': dict(version=VERSION, role=role)}
    for block in BLOCKS:
        for key in block:
            if key in view:
                ordered[key] = view[key]
    ordered.update({key: value for key, value in view.items() if key not in ordered})
    return ordered


def route_facts(view, uid):
    """Read-only diagnostic expansion of the provider's route table."""
    options = view.get('member_region_choices', {}).get(uid, {})
    columns = view.get('route_columns')
    if not columns:
        return copy.deepcopy(options)
    return {rid: {key: copy.deepcopy(value) for key, value in zip(columns, row)
                  if value != {'missing': True}} for rid, row in options.items()}


def share_executor_contract(context, questions):
    """Expose the final (including coordinate) contract to every isolated question.

    Provider evaluates each question against the shared state, not sibling
    instructions or answers. Store the authored rules once, after projection,
    and leave each question's actor/branch-specific task self-contained.
    Does not change criteria, answers, scheduling or engine admission.
    """
    view, offered = copy.deepcopy(context), copy.deepcopy(questions)
    common = offered['intent'].get('instructions', '')
    view.setdefault('prompt_contract', {}).update(
        combat_version=VERSION, question_evaluation='independent_same_state',
        shared_instructions=common)
    offered['intent']['instructions'] = '为当前小队选择本轮行动模式，结合共享状态的实际移动、射线和风险，只选本题候选；其他题是预选参数，不是已生效决策。'
    for question in offered.values():
        question['instructions'] = (
            '先读共享状态 prompt_contract.shared_instructions 的任务、事实与坐标规则。'
            '本题独立判断，不可看到本轮其他题的答案；只回答本题列出的合法选项。\n'
            + question.get('instructions', ''))
    return view, offered
