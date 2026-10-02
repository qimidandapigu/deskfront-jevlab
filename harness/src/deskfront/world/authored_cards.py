"""Authored stationery desks, before model selection, never a runtime rewrite.

The earlier corner-socket catalogues remain available for saved-map replay.
CURATED_CARDS is the new author library: objects can occupy the centre and the
navigation layer derives actual routes from the final geometry. Rotating a card
does not create another catalogue entry.
"""

# Dimensions are collision/visual dimensions together. Keep recognisable hero
# objects larger than hand tools; all cards can rotate on the narrow desk axis.
SHAPES = {
    'bookstack': (.18,.13,.14), 'book_city': (.17,.19,.08),
    'book_atlas': (.19,.16,.08), 'novel': (.17,.19,.08),
    'crate': (.21,.10,.08), 'desk_divider': (.22,.05,.25),
    'printer': (.22,.18,.16), 'laptop': (.22,.17,.17),
    'tissues': (.20,.13,.12), 'file_rack': (.16,.12,.23),
    'warehouse': (.20,.16,.18), 'gabion': (.18,.09,.08),
    'mug': (.085,.085,.11), 'mouse': (.105,.07,.045),
    'ruler': (.21,.025,.012), 'stapler': (.105,.05,.05),
    'tape': (.075,.075,.055), 'phone': (.065,.11,.025),
    'calculator': (.075,.11,.035), 'pipe': (.18,.075,.055),
    'sandbag': (.18,.045,.043),
    'concrete': (.18,.055,.23), 'drum': (.065,.065,.17),
}


def item(asset, corner, turn=0, dx=0, dz=0):
    """An explicitly authored corner socket; no model output is changed here."""
    width,depth,height=SHAPES[asset]
    if turn:width,depth=depth,width
    x=(-1 if 'w' in corner else 1)*(min(.20,.28-width/2))
    z=(-1 if 'n' in corner else 1)*(min(.21,.28-depth/2))
    return (round(x+dx,3),round(z+dz,3),width,depth,asset,height)


def desk(label,purpose,heroes,*parts,theme='stationery_workbench'):
    return dict(label=label,purpose=purpose,family=purpose,theme=theme,
                hero_assets=list(heroes),parts=list(parts))


# These are 32 different desks. Orientation is a separate JEV choice, not four
# entries masquerading as four different designs.
AUTHORED_CARDS = {
    'coding_laptop_notes':desk('代码工作台／电脑、笔记与抽纸','coding',('laptop','tissues'),
        item('laptop','nw'),item('bookstack','ne',1),item('tissues','sw'),item('mouse','se')),
    'coding_printer_buffer':desk('输出工作台／打印机与文件缓冲区','coding',('printer','laptop'),
        item('printer','ne'),item('laptop','sw',1),item('gabion','nw'),item('phone','se')),
    'coding_dual_reference':desk('查阅工作台／电脑夹在两本参考书之间','coding',('laptop','book_atlas'),
        item('book_atlas','nw',1),item('laptop','ne'),item('book_city','se')),
    'coding_screened_station':desk('屏风工作台／隔板侧翼与电脑转角','coding',('desk_divider','laptop'),
        item('desk_divider','nw',1),item('laptop','sw'),item('warehouse','ne'),item('mug','se')),
    'archive_binder_wing':desk('档案翼／纸盒、文件架与卡片箱','archive',('warehouse','file_rack'),
        item('warehouse','nw'),item('file_rack','sw',1),item('gabion','ne'),item('stapler','se'),theme='stationery_storage'),
    'archive_card_sorter':desk('卡片分拣台／双卡盒与隔板','archive',('gabion','desk_divider'),
        item('gabion','nw',1),item('gabion','se'),item('desk_divider','ne',1),item('phone','sw'),theme='stationery_storage'),
    'archive_city_volumes':desk('城市资料库／城市书、地图与纸盒','archive',('book_city','warehouse'),
        item('book_city','nw'),item('book_atlas','sw',1),item('warehouse','se'),item('ruler','ne'),theme='stationery_storage'),
    'archive_biography_stack':desk('人物资料库／传记与双层文档','archive',('novel','warehouse'),
        item('novel','ne',1),item('warehouse','nw'),item('bookstack','se'),item('tape','sw'),theme='stationery_storage'),
    'drafting_atlas_rulers':desk('制图桌／地图册、隔板与刻度尺','drafting',('book_atlas','desk_divider'),
        item('book_atlas','nw'),item('desk_divider','sw'),item('tissues','ne'),item('ruler','se'),theme='writing_desk'),
    'drafting_pencil_island':desk('手绘桌／铅笔岛与笔袋围边','drafting',('crate','book_atlas'),
        item('crate','ne',1),item('book_atlas','sw'),item('gabion','se',1),item('pipe','nw'),theme='writing_desk'),
    'drafting_screened_plan':desk('图纸审阅桌／双隔板夹地图册','drafting',('desk_divider','book_atlas'),
        item('desk_divider','nw'),item('desk_divider','sw',1),item('book_atlas','ne'),item('calculator','se'),theme='writing_desk'),
    'drafting_calculator_reference':desk('尺寸核算桌／两类参考书与计算器','drafting',('book_atlas','book_city'),
        item('book_atlas','ne',1),item('book_city','sw'),item('tissues','se'),item('calculator','nw'),theme='writing_desk'),
    'refreshment_tissue_books':desk('茶歇阅读桌／抽纸、城市书与水杯','refreshment',('tissues','book_city'),
        item('tissues','nw',1),item('book_city','ne'),item('crate','sw'),item('mug','se')),
    'refreshment_coffee_archive':desk('咖啡资料桌／纸盒边的杯子与传记','refreshment',('warehouse','novel'),
        item('warehouse','sw'),item('novel','se',1),item('tissues','ne'),item('mug','nw')),
    'refreshment_printer_break':desk('打印间茶歇桌／打印机、抽纸与卡盒','refreshment',('printer','tissues'),
        item('printer','nw'),item('tissues','se',1),item('gabion','ne'),item('mug','sw')),
    'refreshment_screened_cup':desk('隔板休息角／隔板后方的阅读与水杯','refreshment',('desk_divider','novel'),
        item('desk_divider','se'),item('novel','nw'),item('crate','ne',1),item('mug','sw')),
    'packing_tape_parcels':desk('封装桌／双纸盒与胶带','packing',('warehouse','crate'),
        item('warehouse','nw'),item('warehouse','se',1),item('crate','ne'),item('tape','sw',dz=-.055),item('stapler','sw',dz=.045),theme='stationery_storage'),
    'packing_cards_pouch':desk('卡片寄送桌／卡片盒、笔袋与纸盒','packing',('gabion','warehouse'),
        item('gabion','sw',1),item('warehouse','ne'),item('crate','nw'),item('stapler','se'),theme='stationery_storage'),
    'packing_dispatch_printer':desk('出库打印台／打印机与发货资料','packing',('printer','warehouse'),
        item('printer','se'),item('warehouse','nw',1),item('book_atlas','ne'),item('tape','sw'),theme='stationery_storage'),
    'packing_binder_courtyard':desk('打包围合台／文件架、纸盒与隔板','packing',('file_rack','desk_divider'),
        item('file_rack','nw'),item('warehouse','sw'),item('desk_divider','ne'),item('pipe','se'),theme='stationery_storage'),
    'study_city_notebook':desk('城市阅读桌／城市书、笔记与卡片','study',('book_city','bookstack'),
        item('book_city','ne'),item('bookstack','sw',1),item('gabion','nw'),item('phone','se'),theme='writing_desk'),
    'study_atlas_laptop':desk('旅行研究桌／地图册、电脑与资料盒','study',('book_atlas','laptop'),
        item('book_atlas','sw'),item('laptop','se'),item('gabion','ne',1),item('mouse','nw'),theme='writing_desk'),
    'study_biography_corner':desk('人物阅读角／传记、抽纸与笔袋','study',('novel','tissues'),
        item('novel','nw',1),item('tissues','ne'),item('crate','se',1),item('mug','sw'),theme='writing_desk'),
    'study_reference_gallery':desk('书册展台／传记、城市书与地图册','study',('novel','book_city','book_atlas'),
        item('novel','nw'),item('book_city','ne',1),item('book_atlas','sw'),item('bookstack','se',1),theme='writing_desk'),
    'admin_calculator_files':desk('财务桌／文件架、账册与计算器','admin',('file_rack','bookstack'),
        item('file_rack','ne',1),item('bookstack','se'),item('warehouse','sw'),item('calculator','nw')),
    'admin_phone_notebooks':desk('接待桌／抽纸、记录册与电话','admin',('tissues','gabion'),
        item('tissues','ne'),item('bookstack','nw'),item('gabion','sw',1),item('phone','se')),
    'admin_print_queue':desk('打印队列桌／打印机与两侧待处理纸盒','admin',('printer','warehouse'),
        item('printer','nw',1),item('warehouse','ne'),item('gabion','se'),item('stapler','sw')),
    'admin_divider_registry':desk('登记桌／文件架转角与隔板','admin',('desk_divider','file_rack'),
        item('desk_divider','nw',1),item('file_rack','se'),item('book_city','sw'),item('calculator','ne')),
    'hobby_pencil_case':desk('手账工具桌／笔袋、笔记与卡片','hobby',('crate','gabion'),
        item('crate','nw',1),item('bookstack','se'),item('gabion','ne'),item('pipe','sw'),theme='writing_desk'),
    'hobby_tape_atlas':desk('旅行剪贴桌／地图册、纸盒与胶带','hobby',('book_atlas','warehouse'),
        item('book_atlas','ne'),item('warehouse','se'),item('tissues','sw',1),item('tape','nw'),theme='writing_desk'),
    'hobby_notes_workbench':desk('创作工作台／电脑、传记与工具包','hobby',('laptop','novel'),
        item('laptop','sw'),item('novel','ne'),item('crate','se'),item('pipe','nw'),theme='writing_desk'),
    'hobby_tissue_screen':desk('清理中的手工桌／隔板、抽纸与纸盒','hobby',('desk_divider','tissues'),
        item('desk_divider','sw'),item('tissues','nw',1),item('warehouse','se'),item('tape','ne'),theme='writing_desk'),
}


# Keep the existing eight recognisable workbench IDs, correcting their authored
# footprint rather than rotating a rectangle beyond the narrower desk edge.
WORKBENCH_CARDS = {
    'divider_mouse_corner':desk('桌面隔板与鼠标转角','coding',('desk_divider','mouse'),
        item('desk_divider','nw'),item('file_rack','sw'),item('book_city','ne'),item('mouse','se')),
    'printer_coffee_station':desk('打印机与咖啡工作台','admin',('printer','mug'),
        item('printer','nw'),item('file_rack','sw'),item('tissues','ne'),item('mug','se')),
    'tissues_cup_ruler':desk('抽纸、杯子与尺子区','refreshment',('tissues','mug'),
        item('tissues','nw'),item('book_atlas','ne'),item('crate','sw'),item('mug','se',dz=-.055),item('ruler','se',dz=.035)),
    'biography_laptop_desk':desk('传记与电脑办公区','study',('novel','laptop'),
        item('novel','nw'),item('laptop','se'),item('gabion','ne',1),item('mouse','sw')),
    'cardbox_file_rack':desk('卡片、文件架与订书器','archive',('gabion','file_rack'),
        item('gabion','nw'),item('gabion','se'),item('file_rack','sw'),item('stapler','ne')),
    'pencil_pouch_tape':desk('铅笔、笔袋与胶带区','hobby',('crate','pipe'),
        item('crate','nw'),item('bookstack','se'),item('warehouse','sw'),item('pipe','ne',dz=-.018),item('tape','ne',dz=.09)),
    'citybook_tissues_phone':desk('城市书、抽纸与手机区','study',('book_city','tissues'),
        item('book_city','nw'),item('tissues','se',1),item('gabion','ne'),item('phone','sw')),
    'atlas_ruler_calculator':desk('地图册、尺子与计算器区','drafting',('book_atlas','ruler'),
        item('book_atlas','nw'),item('file_rack','ne'),item('crate','sw'),item('ruler','se',dz=.035),item('calculator','se',dz=-.055)),
}


BASE_CARDS = {
    'open':desk('双侧笔记与笔袋掩护区','hobby',('bookstack','crate'),
        item('bookstack','nw'),item('crate','se'),item('gabion','ne'),theme='writing_desk'),
    'books':desk('三类书册交错掩护区','study',('bookstack','book_city'),
        item('bookstack','nw'),item('book_city','sw'),item('book_atlas','se'),theme='writing_desk'),
    'crates':desk('笔袋、纸盒与订书器收纳区','packing',('crate','warehouse'),
        item('crate','nw'),item('warehouse','se'),item('gabion','sw'),item('stapler','ne'),theme='stationery_storage'),
    'sandbags':desk('橡皮与文件架支援区','admin',('file_rack','sandbag'),
        item('sandbag','sw'),item('file_rack','nw'),item('bookstack','ne'),item('tissues','se')),
}


CURATED_SCALE = 1.1
# Keep the desk readable at battle zoom: a laptop, printer or archive box should
# dominate the composition, while hand tools remain visibly smaller. These
# multipliers affect the authored collision box and the mesh together.
CURATED_ASSET_SCALE = {
    'laptop': 1.2, 'printer': 1.2, 'warehouse': 1.2,
    'crate': 1.2, 'desk_divider': 1.1, 'file_rack': 1.1,
    'mouse': .85, 'mug': .9, 'ruler': .9, 'stapler': .85,
    'tape': .9, 'phone': .85, 'calculator': .9,
    'pipe': .9, 'sandbag': .9,
}

# One canonical size across desks AND free builder edits. Larger equipment
# establishes the hierarchy without inflating mice, rulers or other hand tools.
CURRENT_DIMENSIONS = {
    'concrete': (.18, .055, .23),
    'drum': (.065, .065, .17),
    'warehouse': (.38, .30, .28),
    'laptop': (.35, .27, .25),
    'printer': (.36, .28, .23),
    'bookstack': (.198, .143, .066),
    'book_city': (.187, .209, .0495),
    'book_atlas': (.209, .176, .0495),
    'novel': (.187, .209, .0495),
}


def current_dimensions(asset):
    """One physical size per stationery kind in the current generation."""
    if asset in CURRENT_DIMENSIONS:
        return CURRENT_DIMENSIONS[asset]
    scale = CURATED_SCALE * CURATED_ASSET_SCALE.get(asset, 1.0)
    return tuple(round(value * scale, 4) for value in SHAPES[asset])


def placed(asset, x, z, turn=0):
    """Author a curated prop with a category-specific size hierarchy.

    Use authored world positions and scale all three dimensions so the soldier radius
    fits beside outer desk objects. This is fixed author data visible to JEV,
    never a change to a submitted map; the legacy socket cards keep their scale.
    """
    width, depth, height = current_dimensions(asset)
    if turn % 2:
        width, depth = depth, width
    return (round(x, 4), round(z, 4), width, depth, asset, height)


def curated(label, purpose, heroes, layout, composition, route_character, *parts,
            theme='stationery_workbench', allowed_rotations=(0,90,180,270)):
    card = desk(label, purpose, heroes, *parts, theme=theme)
    card.update(layout=layout, composition=composition, route_character=route_character,
                author_scale=CURATED_SCALE, asset_scale_profile='canonical_stationery_v2',
                allowed_rotations=list(allowed_rotations))
    return card


# At least three different compositions for each desk use. This is an authoring
# plan, not a quota imposed on JEV: every table can choose every card, including
# repetitions. Hero objects, occupied space and internal passage shape differ;
# Some desks carry one dominant object; others keep a two-piece composition.
CURATED_CARDS = {
    'code_laptop_island': curated(
        '电脑岛／从屏幕两侧绕行', 'coding', ('laptop', 'mouse'), 'central_island',
        '电脑占据桌心，鼠标留在手边。',
        '屏幕切断桌心直射线，两侧留出绕行空间。',
        placed('laptop', -0.0216, -0.0038), placed('mouse', 0.127, 0.185)),
    'code_screened_bay': curated(
        '屏风工位／向右开口的工作湾', 'coding', ('desk_divider', 'laptop'), 'c_bay',
        '隔板在后沿，电脑向下错开形成工作湾。',
        '隔板后适合短暂停留，两侧开口提供接近和撤出路线。',
        placed('desk_divider', -0.058, -0.217), placed('laptop', -0.083, 0.139)),
    'code_offset_backup': curated(
        '单电脑工作台／桌心电脑', 'coding', ('laptop',), 'single_landmark',
        '一台标准尺寸电脑单独放在桌心。',
        '电脑形成中央遮挡，桌面外缘保持通行。',
        placed('laptop', 0, 0)),

    'archive_central_files': curated(
        '档案主箱／单件纸盒', 'archive', ('warehouse',), 'single_landmark',
        '一个标准尺寸档案纸盒单独放在桌心。',
        '纸盒遮住桌心，士兵从外缘绕过。',
        placed('warehouse', -0.025, 0.0), theme='stationery_storage'),
    'archive_catalogue_alley': curated(
        '目录查阅桌／城市书与订书器', 'archive', ('book_city', 'stapler'), 'edge_archive',
        '橙色城市书偏向左后方，红色订书器放在右前沿。',
        '低书册与工具之间留出观察和通过空间。',
        placed('book_city', -0.09, -0.10), placed('stapler', 0.15, 0.15),
        theme='stationery_storage'),
    'archive_reference_crescent': curated(
        '资料弯月／双书册围出阅读口', 'archive', ('novel', 'book_atlas'), 'book_crescent',
        '传记贴左侧，地图册横放后沿，右侧留白。',
        '分开的低书册保护左翼，主要活动空间沿右侧弯折。',
        placed('novel', -0.167, -0.1402),
        placed('book_atlas', 0.1205, -0.184), theme='stationery_storage'),

    'draft_atlas_island': curated(
        '地图审阅桌／地图册居中', 'drafting', ('book_atlas', 'ruler'), 'drawing_island',
        '地图册横放中央，尺子留在手边。',
        '中央低遮挡两侧开阔，可从不同方向观察再推进。',
        placed('book_atlas', 0.0045, -0.018), placed('ruler', 0.063, -0.25),
        theme='writing_desk'),
    'draft_parallel_screens': curated(
        '评图桌／错位双隔板', 'drafting', ('desk_divider',), 'offset_screens',
        '两块隔板一前一后错位。',
        '两道高屏风将长射线切成分段，开口向不同侧偏移。',
        placed('desk_divider', -0.0539, -0.1181), placed('desk_divider', 0.1224, 0.0932),
        theme='writing_desk'),
    'draft_measurement_edge': curated(
        '测量长台／文具沿边展开', 'drafting', ('crate', 'sandbag'), 'edge_workbench',
        '笔袋靠左边，橡皮守住右侧。',
        '左边轮廓较完整，右侧留出开阔过渡区和低伏射线。',
        placed('crate', -0.168, -0.135, 1), placed('sandbag', 0.126, 0.183),
        theme='writing_desk'),

    'break_tissue_cove': curated(
        '茶歇纸巾湾／抽纸与阅读角', 'refreshment', ('tissues', 'novel'), 'soft_cove',
        '抽纸靠近桌心，传记放左后方。',
        '桌心的抽纸遮住一段视线，书册形成低矮停靠点。',
        placed('tissues', -0.0266, 0.0611), placed('novel', -0.1684, -0.1339, 1)),
    'break_book_conversation': curated(
        '共读茶歇桌／书册与水杯', 'refreshment', ('book_city', 'mug'), 'diagonal_reading',
        '城市书与水杯沿对角错开。',
        '书册打断直冲路线，外围保留互相支援的开口。',
        placed('book_city', -0.102, -0.1018), placed('mug', -0.1838, 0.1675)),
    'break_divider_retreat': curated(
        '隔板休息角／右侧休息口', 'refreshment', ('desk_divider', 'tissues'), 'sheltered_edge',
        '隔板竖在左侧，抽纸与它错开。',
        '高隔板遮住一个方向，向右前方退让时仍有开口。',
        placed('desk_divider', -0.1962, -0.099, 1), placed('tissues', -0.056, 0.1867)),

    'pack_parcel_island': curated(
        '封装岛／纸盒与胶带工作面', 'packing', ('warehouse', 'tape'), 'parcel_island',
        '档案纸盒占据中央，胶带紧靠封装侧。',
        '纸盒提供环绕掩护，低工具靠边避免重复的四角高墙。',
        placed('warehouse', 0.03, 0.071),
        placed('tape', 0.237, -0.137), theme='stationery_storage'),
    'pack_dispatch_channel': curated(
        '寄送通道／大纸盒靠后', 'packing', ('warehouse',), 'dispatch_lane',
        '一个大纸盒靠向左后方，前方留作寄送通道。',
        '高纸盒形成明确的遮挡边界，右侧与前方可绕行。',
        placed('warehouse', -0.08, -0.08),
        theme='stationery_storage'),
    'pack_printer_loading': curated(
        '出单装箱桌／打印机侧装区', 'packing', ('printer', 'stapler'), 'loading_elbow',
        '打印机在左半桌，订书器放在前沿工作边。',
        '打印机挡住一侧视线，另一侧保留推进空间。',
        placed('printer', -0.094, -0.074),
        placed('stapler', -0.043, -0.251), theme='stationery_storage'),

    'study_biography_island': curated(
        '传记阅读岛／书页与笔记', 'study', ('novel', 'bookstack'), 'reading_island',
        '传记横放桌心，蓝色装订笔记本放在侧边。',
        '两件低矮书册保留跨桌视野，右側留出转移空间。',
        placed('novel', 0.0132, -0.0139, 1), placed('bookstack', -0.1929, 0.0913, 1),
        theme='writing_desk'),
    'study_book_terraces': curated(
        '单册阅读桌／桌心地图册', 'study', ('book_atlas',), 'single_landmark',
        '一本标准尺寸地图册单独放在桌心。',
        '书册形成低矮中央遮挡，外缘留出通路。',
        placed('book_atlas', 0, 0), theme='writing_desk'),
    'study_open_reference': curated(
        '查阅桌／地图册与手机', 'study', ('book_atlas', 'phone'), 'reference_elbow',
        '地图册靠左侧，右侧手机单独摆放。',
        '低书册保留一段掩护，另一端保持开阔。',
        placed('book_atlas', -0.0919, -0.1617),
        placed('phone', 0.1705, -0.129), theme='writing_desk'),

    'admin_calculator_counter': curated(
        '财务柜台／中间核算、两侧资料', 'admin', ('file_rack', 'calculator'), 'clerical_counter',
        '文件架横占左中部，计算器留在操作区。',
        '一高一低两组资料遮挡不对称，中央操作区在侧翼打开。',
        placed('file_rack', -0.1284, 0.0186, 1),
        placed('calculator', -0.1231, -0.1913)),
    'admin_reception_pocket': curated(
        '接待记录桌／抽纸后的记录口', 'admin', ('tissues', 'gabion'), 'reception_pocket',
        '抽纸横放桌心前方，卡片盒竖在左边。',
        '两件高度不同的文具留出接待口，右方通路更开放。',
        placed('tissues', 0.0204, -0.0556), placed('gabion', -0.1937, -0.0527, 1)),
    'admin_print_sideboard': curated(
        '单打印机工作台／桌心打印机', 'admin', ('printer',), 'single_landmark',
        '一台标准尺寸打印机单独放在工作台。',
        '打印机形成中央硬遮挡，四周仍有通路。',
        placed('printer', 0, 0)),

    'hobby_pencil_garden': curated(
        '手账工具园／笔袋与铅笔', 'hobby', ('crate', 'pipe'), 'tools_fan',
        '笔袋居中偏左，铅笔横放后沿。',
        '高低短掩体围成不规则工作面，右侧有连续转移空隙。',
        placed('crate', -0.0567, 0.0361, 1), placed('pipe', -0.0934, -0.1738),
        theme='writing_desk'),
    'hobby_scrapbook_bend': curated(
        '旅行剪贴桌／摊开地图与胶带', 'hobby', ('book_atlas', 'tape'), 'scrapbook_bend',
        '地图册靠左横放，胶带单独留在右后方。',
        '低物件之间留出宽活动面，适合观察和通过。',
        placed('book_atlas', -0.1701, -0.0004), placed('tape', 0.1551, -0.1598),
        theme='writing_desk'),
    'hobby_cleanup_courtyard': curated(
        '整理手工桌／隔板与工具围院', 'hobby', ('desk_divider', 'crate'), 'tool_courtyard',
        '隔板横在后沿，笔袋位于左侧。',
        '两件主要遮挡留出中央停留区，前侧保持进出视线。',
        placed('desk_divider', 0.0224, -0.1958), placed('crate', -0.1712, 0.0285, 1),
        theme='writing_desk'),
    'archive_ringbinder_notes': curated(
        '文件夹查阅台／立档与笔记本', 'archive', ('concrete', 'bookstack'), 'binder_elbow',
        '紫色立式文件夹位于左后侧，蓝色笔记本放在右前侧。',
        '竖立文件夹提供窄高遮挡，低笔记本保留视野，两侧可以绕行。',
        placed('concrete', -.105, -.105, 1), placed('bookstack', .11, .11),
        theme='stationery_storage'),
    'hobby_glue_notebook': curated(
        '粘贴手账台／胶棒与笔记本', 'hobby', ('drum', 'bookstack'), 'glue_worktop',
        '黄色旋盖胶棒立在右后侧，蓝色笔记本平放左前侧。',
        '胶棒只形成很窄的高遮挡，笔记本低矮，整体保留开阔通过空间。',
        placed('drum', .155, -.15), placed('bookstack', -.08, .06),
        theme='writing_desk'),

}
