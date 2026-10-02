"""One truthful, geometry-derived description for each distinct desk-cell design."""
from functools import lru_cache

from .region_graph import LIBRARY, PROPS, SELECTABLE_MODULES


LABELS={'concrete':'隔板支脚','novel':'传记书','warehouse':'档案纸盒'}


def direction(dx,dz):
    north='北' if dz<-.06 else '南' if dz>.06 else '中'
    west='西' if dx<-.06 else '东' if dx>.06 else '中'
    return north+west if north!='中' and west!='中' else (north if north!='中' else west)


@lru_cache(maxsize=1)
def cards():
    """Expose the current authored cards; legacy layouts remain replayable only."""
    sample=LIBRARY['cells']['c1r1']
    cx,cz=sample['open']['center']
    result={}
    for module in (*SELECTABLE_MODULES,'fortress_base'):
        part=sample[module]
        items=[]
        for index,(x,z,width,depth,asset,height) in enumerate(part['covers']):
            dx,dz=round(x-cx,3),round(z-cz,3)
            items.append(dict(index=index,asset=asset,name=PROPS.get(asset,{}).get('label',LABELS.get(asset,asset)),
                offset=[dx,dz],position=direction(dx,dz),size=[width,depth],height=height))
        functional=sum(item['height']>=.07 and max(item['size'])>=.14 for item in items)
        result[module]=dict(name=part['label'],items=items,
            purpose=part.get('purpose','general'),family=part.get('family',module),
            allowed_rotations=part.get('allowed_rotations',[0,90,180,270]),
            hero_assets=part.get('hero_assets',list(dict.fromkeys(item['asset'] for item in items))),
            topology=part.get('topology',part.get('layout','')),
            composition=part.get('composition',''),passages=part.get('route_character',''),
            layout=('最终与7件文件墙组合成救援堡垒' if module=='fortress_base' else
                    '、'.join(f"{item['position']}{item['name']}" for item in items) or '没有文具'),
            functional_cover_count=functional,occupied=module=='empty')
    assert len(result)==len(SELECTABLE_MODULES)+1
    return result


def menu():
    return {module:f"{card['name']}｜{card['layout']}｜{card['functional_cover_count']}处有效遮挡"+
        ('｜封闭：不可当入口/出口，也会断开路径' if card['occupied'] else '')
        for module,card in cards().items() if module!='fortress_base'}


def inventory():
    """Ground the planner's theme choices in objects the builder can really select."""
    from collections import Counter
    catalog={key:value for key,value in cards().items() if key not in ('empty','fortress_base')}
    return dict(card_count=len(SELECTABLE_MODULES),
        asset_card_counts=dict(Counter(asset for card in catalog.values()
            for asset in {item['asset'] for item in card['items']})),
        desk_purposes=dict(Counter(card['purpose'] for card in catalog.values())),
        note=f'数量表示有多少张卡包含该物件；全部{len(SELECTABLE_MODULES)}张普通卡均可选。用途和主物件是卡片实际内容，不是引擎自动换皮。')


MODEL_CARD_COLUMNS=('name','purpose','heroes','allowed_rotations','cover_count','occupied',
                    'topology','composition','passages','items')


def model_card(card):
    """Lossless geometry table; shared once instead of expanded per choice."""
    return dict(name=card['name'],purpose=card['purpose'],heroes=card['hero_assets'],
        allowed_rotations=card['allowed_rotations'],
        cover_count=card['functional_cover_count'],occupied=card['occupied'],topology=card['topology'],
        composition=card['composition'],passages=card['passages'],
        items=[[item['asset'],*item['offset'],*item['size'],item['height']] for item in card['items']])


def model_card_row(card):
    """Same facts and item order as model_card, with field names shared once."""
    record=model_card(card)
    return [record[column] for column in MODEL_CARD_COLUMNS]
