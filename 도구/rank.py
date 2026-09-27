"""청담언니 최근 쇼츠 180개 → 섹터 분류 + 종합점수(조회수·댓글·최신성) → 섹터 대표 포함 상위 20개 선정.
사용: python tools/rank.py  (기준일은 BASE_DATE)"""
import json, math, re, datetime, csv, os
import numpy as np

BASE_DATE = datetime.date(2026, 9, 28)
rows = json.load(open('meta/all_rows.json', encoding='utf-8'))
single = [l.strip() for l in open('meta/individual_ids.txt') if l.strip()]
pool = [r for r in rows if r['id'] not in single and (r['dur'] or 999) <= 180 and (r['date'] or '') >= '20260301']

SECTORS = [  # (키, 이름, 판별 규칙) — 위에서부터 먼저 맞는 것 1개
    ('ng', '🤣 NG·실패 코미디', r'NG|비하인드|절망|안되는날|심폐소생술|이렇게\s*하세요|이렇게\s*만드세요|이렇게\s*튀기세요|깨진데|부러진데|이렇게하세요'),
    ('mass', '📦 대량생산', r'대량생산'),
    ('asmr', '🔊 ASMR 부수기·으깨기', r'asmr|ASMR|깨기|으깨기'),
    ('ad', '🛍 협찬·광고', r'GS25|FEELIT|원픽|#rain|메롱바'),
    ('life', '👩 일상·기념일 브이로그', r'결혼기념일|생신|광안리|상어와|북카페|나이트레이스|물놀이|초를 끄기|드론쇼|밥상 투어'),
    ('drink', '🧊 에이드·음료 빌드', r'에이드|스무디|슬러시|라떼|카페음료|밀크|콩국'),
    ('ice', '🍧 아이스·과일 디저트', r'아이스|철판|젤라또|샤베트|멜론콘|과일칩|과일 ?asmr|빙수|주상절리'),
    ('dessert', '🎂 케이크·빵·떡 디저트', r'케이크|찹쌀떡|두쫀쿠|산도|샌드|팬케이크|빵|쿠키|설기|마카롱|토스트|베이글|프링글스|젤리|잼|초코'),
    ('cook', '🍳 요리·한끼', r'.'),
]
def sector(t):
    for k, name, pat in SECTORS:
        if re.search(pat, t or ''):
            return k
    return 'cook'
SNAME = {k: n for k, n, _ in SECTORS}

def pct_rank(vals):
    a = np.array(vals, dtype=float); order = a.argsort().argsort()
    return order / max(len(a) - 1, 1)

for r in pool:
    d = datetime.date(int(r['date'][:4]), int(r['date'][4:6]), int(r['date'][6:]))
    r['age_days'] = max((BASE_DATE - d).days, 1)
    r['vpd'] = r['views'] / r['age_days']
    r['cpk'] = round((r['comments'] or 0) / max(r['views'], 1) * 1000, 3)
    r['sector'] = sector(r['title'])
pv = pct_rank([math.log10(r['views'] + 1) for r in pool])
pc = pct_rank([math.log10((r['comments'] or 0) + 1) for r in pool])
pd_ = pct_rank([r['vpd'] for r in pool])
pr = pct_rank([-r['age_days'] for r in pool])
for i, r in enumerate(pool):
    # 조회수 35% · 댓글 25% · 일평균 조회수 25%(최신+조회수) · 최신성 15%
    r['score'] = round(100 * (0.35 * pv[i] + 0.25 * pc[i] + 0.25 * pd_[i] + 0.15 * pr[i]), 1)
pool.sort(key=lambda r: -r['score'])

# 선정 규칙(투명하게 재현 가능):
# ① 모든 섹터 1위 ② 영상 7개 이상 섹터는 2위도(단 2위 점수 75 이상) ③ 나머지는 종합점수 순, 섹터당 최대 4개로 20개까지
# ④ ③에서 마지막(20번째)으로 들어간 영상과 점수 차 1.0 이내인 후보는 동점대로 보고 함께 포함
picked, per = [], {}
def take(r):
    picked.append(r); per[r['sector']] = per.get(r['sector'], 0) + 1
for k, _, _ in SECTORS:
    cand = [r for r in pool if r['sector'] == k]
    if cand: take(cand[0])
    if len(cand) >= 7 and len(cand) > 1 and cand[1]['score'] >= 75: take(cand[1])
last = None
for r in pool:
    if len(picked) >= 20: break
    if r in picked or per.get(r['sector'], 0) >= 4: continue
    take(r); last = r['score']
for r in pool:
    if r not in picked and per.get(r['sector'], 0) < 4 and last - r['score'] <= 1.0:
        take(r)
picked.sort(key=lambda r: -r['score'])
for i, r in enumerate(picked, 1):
    r['rank'] = i
med_views = float(np.median([r['views'] for r in pool]))
out = {'base_date': str(BASE_DATE), 'pool_size': len(pool), 'pool_range': [min(r['date'] for r in pool), max(r['date'] for r in pool)],
       'median_views': med_views, 'weights': '조회수(log) 35% · 댓글(log) 25% · 일평균조회수 25% · 최신성 15% (180개 안에서 백분위)',
       'sectors': {k: {'name': SNAME[k], 'count': sum(1 for r in pool if r['sector'] == k),
                       'median_views': float(np.median([r['views'] for r in pool if r['sector'] == k] or [0])),
                       'top_views': max([r['views'] for r in pool if r['sector'] == k] or [0])} for k, _, _ in SECTORS},
       'picked': picked, 'pool': pool}
json.dump(out, open('data/ranking.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
with open('data/ranking_pool.csv', 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f); w.writerow(['종합점수', '섹터', '업로드', '경과일', '길이', '조회수', '일평균', '좋아요', '댓글', '댓글/1천뷰', 'id', '제목'])
    for r in pool:
        w.writerow([r['score'], SNAME[r['sector']], r['date'], r['age_days'], r['dur'], r['views'], round(r['vpd']), r['likes'], r['comments'], r['cpk'], r['id'], r['title']])
print('pool', len(pool), 'median views', med_views)
for k, v in out['sectors'].items(): print(f"  {v['name']}: {v['count']}개 · 중앙값 {v['median_views']:,.0f} · 최고 {v['top_views']:,}")
print('--- picked 20')
for r in picked:
    print(f"{r['rank']:2d} {r['score']:5.1f} {SNAME[r['sector']]:<14} {r['date']} {r['views']:>11,} c{r['comments']:>4} vpd{r['vpd']:>10,.0f} {r['id']} {r['title'][:50]}")
