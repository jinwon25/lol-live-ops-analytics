"""공식 Data Dragon의 챔피언 기술 설명. 알려진 챔피언만 조회하고 HTML은 제거한다."""
import asyncio
import html
import re
import httpx
from service.evidence import catalogue

cache = {}
lock = asyncio.Lock()


def plain(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value))).strip()


async def abilities(champion_id):
    cat = catalogue()
    version = cat['version']
    key = (version, champion_id)
    if key in cache:
        return cache[key]
    if not any(c['id'] == champion_id for c in cat['champions']):
        return {'available': False, 'skills': []}
    async with lock:
        if key in cache:
            return cache[key]
        source = f'https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion/{champion_id}.json'
        try:
            async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
                r=await client.get(source); r.raise_for_status(); raw=r.json()['data'][champion_id]
            skills=[]
            for hotkey,spell in [('P',raw['passive']),*zip('QWER',raw['spells'])]:
                filename=spell.get('image',{}).get('full','')
                valid=bool(re.fullmatch(r'[A-Za-z0-9_.-]+\.png',filename))
                folder='passive' if hotkey=='P' else 'spell'
                skills.append({'key':hotkey,'name':plain(spell['name']),'description':plain(spell['description']),
                               'image_url':f'https://ddragon.leagueoflegends.com/cdn/{version}/img/{folder}/{filename}' if valid else None})
            result={'available':True,'title':plain(raw['title']),'skills':skills,
                    'ally_tips':[plain(t) for t in raw.get('allytips',[])], 'enemy_tips':[plain(t) for t in raw.get('enemytips',[])], 'source_url':source}
            cache[key]=result
            return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            return {'available':False,'skills':[],'source_url':source}
