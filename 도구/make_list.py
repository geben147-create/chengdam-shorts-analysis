"""분석 대상 30개 목록(data/videos.json): 청담언니 선정 영상(c01~) + 사용자가 준 개별 영상 8개(s1~s8, 준 순서)."""
import json

rk = json.load(open('data/ranking.json', encoding='utf-8'))
rows = {r['id']: r for r in json.load(open('meta/all_rows.json', encoding='utf-8'))}
vids = []
for r in rk['picked']:
    vids.append({'key': f"c{r['rank']:02d}", 'group': 'chengdam', 'rank': r['rank'], 'id': r['id'], 'title': r['title'],
                 'channel': r['ch'], 'subs': r['subs'], 'sector': r['sector'], 'sector_name': rk['sectors'][r['sector']]['name'],
                 'date': r['date'], 'dur': r['dur'], 'views': r['views'], 'likes': r['likes'], 'comments': r['comments'],
                 'score': r['score'], 'vpd': round(r['vpd']), 'age_days': r['age_days']})
single = [l.strip() for l in open('meta/individual_ids.txt') if l.strip()]
for i, vid in enumerate(single, 1):
    r = rows[vid]
    vids.append({'key': f"s{i}", 'group': 'single', 'rank': i, 'id': vid, 'title': r['title'], 'channel': r['ch'],
                 'subs': r['subs'], 'handle': r['handle'], 'date': r['date'], 'dur': r['dur'], 'views': r['views'],
                 'likes': r['likes'], 'comments': r['comments']})
json.dump(vids, open('data/videos.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(vids), 'videos')
