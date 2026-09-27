"""큰 JSON을 나눠 쓰기 위한 합치기 도구.
videos/<키>/analysis_head.json(shots 빼고 전부) + shots_part1.json, shots_part2.json … (각각 컷 객체 리스트) → analysis.json
사용: python tools/merge_shots.py <키>"""
import sys, os, json, glob, re

key = sys.argv[1]
d = os.path.join('videos', key)
head = json.load(open(os.path.join(d, 'analysis_head.json'), encoding='utf-8'))
parts = sorted(glob.glob(os.path.join(d, 'shots_part*.json')), key=lambda p: int(re.findall(r'(\d+)\.json$', p)[0]))
shots = []
for p in parts:
    shots += json.load(open(p, encoding='utf-8'))
shots.sort(key=lambda s: s['n'])
head['shots'] = shots
json.dump(head, open(os.path.join(d, 'analysis.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{key}: {len(parts)}개 파트 → shots {len(shots)}개 합침 → analysis.json')
