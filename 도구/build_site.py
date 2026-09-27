"""분석 JSON → 공개용 사이트(HTML·TXT·MD·데이터·편집키트) 생성.
사용: python tools/build_site.py <출력폴더> [--private]
--private: 컷 캡처 사진을 넣은 개인용(비공개) 버전 — 공개 저장소에 올리지 말 것"""
import sys, os, json, csv, shutil, statistics as st, html, re, glob
import markdown as mdlib

OUT = sys.argv[1]
PRIVATE = '--private' in sys.argv
BASE = '2026-09-28'
VIDS = json.load(open('data/videos.json', encoding='utf-8'))
RK = json.load(open('data/ranking.json', encoding='utf-8'))
SNAME = {k: v['name'] for k, v in RK['sectors'].items()}
SUBJ = {'face': '얼굴', 'face_hands': '얼굴+손', 'hands': '손+물체', 'object': '물체만', 'person': '몸(얼굴 없음)', 'text': '글자 카드', 'mixed': '혼합'}
CUT = {'hard': '하드컷', 'jump': '점프컷', 'match': '매치컷', 'whip': '휩 전환', 'dissolve': '디졸브', 'flash': '섬광 프레임', 'false': '(검출 오류·같은 장면)'}
ROLE = {'hook': '훅', 'setup': '셋업', 'build': '빌드업', 'tension': '긴장', 'reveal': '공개', 'payoff': '보상', 'reaction': '리액션',
        'rehook': '재훅', 'cta': '행동유도', 'loop': '루프', 'broll': '보조컷'}


def load(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def esc_pipe(s):
    return str(s if s is not None else '').replace('|', '／').replace('\n', ' ')


def fnum(x, d=0):
    try:
        return f'{x:,.{d}f}'
    except (TypeError, ValueError):
        return str(x)


def ymd(s):
    return f'{s[:4]}-{s[4:6]}-{s[6:]}' if s and len(s) == 8 else str(s)


def yt(vid, t=None):
    return f'https://www.youtube.com/watch?v={vid}' + (f'&t={int(t)}s' if t is not None else '')


def title_short(t, n=42):
    t = re.sub(r'\s*#\S+', '', t or '').strip()
    return t if len(t) <= n else t[:n] + '…'


def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    out += ['| ' + ' | '.join(esc_pipe(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def bullets(items, num=False):
    return '\n'.join(f'{i}. {x}' if num else f'- {x}' for i, x in enumerate(items, 1)) if items else '- (없음)'


def label(v):
    return f"청담언니 {v['rank']}위" if v['group'] == 'chengdam' else f"개별 영상 {v['rank']}"


def fname(v):
    return f"청담언니_{v['rank']:02d}위" if v['group'] == 'chengdam' else f"개별영상_{v['rank']}"


# ---------- 일반 렌더러(종합 JSON용) ----------
def render_any(o, level=3):
    if isinstance(o, dict):
        parts = []
        for k, v in o.items():
            if isinstance(v, (dict, list)) and v:
                parts.append(f"{'#' * min(level, 6)} {k}\n\n{render_any(v, level + 1)}")
            else:
                parts.append(f'- **{k}**: {v}')
        return '\n\n'.join(parts)
    if isinstance(o, list):
        if o and all(isinstance(x, dict) for x in o):
            keys = []
            for x in o:
                for k in x:
                    if k not in keys:
                        keys.append(k)
            simple = all(not isinstance(x.get(k), dict) for x in o for k in keys)
            if simple and len(keys) <= 9:
                rows = [[', '.join(map(fmt_inline, x.get(k))) if isinstance(x.get(k), list) else x.get(k, '') for k in keys] for x in o]
                return table(keys, rows)
            return '\n\n'.join(render_any(x, level) for x in o)
        return bullets([fmt_inline(x) for x in o])
    return str(o)


def fmt_inline(x):
    if isinstance(x, dict):
        return ' · '.join(f'{k}: {fmt_inline(v)}' for k, v in x.items())
    if isinstance(x, list):
        return ', '.join(fmt_inline(i) for i in x)
    return str(x)


# ---------- 영상 1개 ----------
def stats(a, cj, au, fc):
    shots = cj['shots']; dur = cj['duration']
    real = [s for s, x in zip(shots, a['shots']) if x.get('cut_type') != 'false'] if a else shots
    ds = [s['dur'] for s in shots]
    n_real = len(real) if a else len(shots)
    tot = sum(ds) or 1
    w = {}
    if a:
        for s, x in zip(shots, a['shots']):
            w[x['subj']] = w.get(x['subj'], 0) + s['dur']
    face = (w.get('face', 0) + w.get('face_hands', 0)) / tot * 100
    hands = (w.get('hands', 0) + w.get('face_hands', 0)) / tot * 100
    obj = w.get('object', 0) / tot * 100
    return {'dur': dur, 'n': len(shots), 'n_real': n_real, 'avg': dur / max(n_real, 1), 'med': st.median(ds), 'cpm': n_real / dur * 60,
            'min': min(ds), 'max': max(ds), 'lufs': (au or {}).get('ebur128', {}).get('I_LUFS'), 'ons': (au or {}).get('onsets_per_s'),
            'sync': (au or {}).get('cut_onset_sync_pct'), 'chance': (au or {}).get('chance_sync_pct'), 'hf': (au or {}).get('hf_ratio_4k_mean'),
            'sil': (au or {}).get('silence_ratio'), 'face_cv': (fc or {}).get('face_time_ratio'), 'face': face, 'hands': hands, 'obj': obj,
            'size': cj.get('size')}


def md_video(v, a, cj, au, fc, img_rel=None):
    S = stats(a, cj, au, fc)
    L = [f"# {label(v)} 「{title_short(v['title'], 60)}」 — {a['fmt']}", '']
    meta = [f"원본: {yt(v['id'])}", f"채널: {v['channel']}" + (f" (구독 {fnum(v['subs'])})" if v.get('subs') else ''),
            f"업로드 {ymd(v['date'])}", f"조회수 {fnum(v['views'])}", f"좋아요 {fnum(v['likes'])}", f"댓글 {fnum(v['comments'])}"]
    if v['group'] == 'chengdam':
        meta += [f"섹터 {SNAME[v['sector']]}", f"종합점수 {v['score']} (일평균 조회수 {fnum(v['vpd'])})"]
    L += ['- ' + ' · '.join(meta),
          f"- 길이 {S['dur']:.1f}초 · 컷 {S['n_real']}개(검출 {S['n']}) · 평균 컷 {S['avg']:.2f}초 · 중앙값 {S['med']:.2f}초 · 분당 {S['cpm']:.0f}컷 · "
          f"가장 짧은 컷 {S['min']:.2f}초 · 가장 긴 컷 {S['max']:.2f}초",
          f"- 소리: 음량 {S['lufs']} LUFS · 초당 타격음(온셋) {S['ons']} · 컷-타격음 일치 {S['sync']}% (우연 기준 {S['chance']}%) · "
          f"고역(4kHz+) 비율 {S['hf']} · 무음 {round((S['sil'] or 0) * 100)}%",
          f"- 화면 구성(컷 길이 가중): 얼굴 {S['face']:.0f}% · 손 {S['hands']:.0f}% · 물체만 {S['obj']:.0f}% (자동 얼굴 검출 참고값 {round((S['face_cv'] or 0) * 100)}%)", '',
          '## 한 줄 요약', a['logline'], '']
    h = a['hook']
    L += [f"## 🎣 소재·어그로(훅) — 훅 점수 {h['score']}/10", '',
          f"- **어그로 유형**: {' · '.join(h['aggro_types'])}",
          f"- **제목 장치**: {h['title_hook']}", f"- **첫 프레임**: {h['first_frame']}", f"- **0~1초**: {h['first_1s']}",
          f"- **0~3초**: {h['first_3s']}", f"- **첫 자막/문구 의도**: {h['text_hook']}", f"- **약속 → 회수**: {h['promise_payoff']}",
          f"- **중간 재훅·오픈 루프**: {' / '.join(h['retention_devices'])}", f"- **엔딩·루프**: {h['ending_loop']}",
          f"- **훅 점수 이유**: {h['score_note']}", '',
          '### 소재', f"- **소재**: {a['topic']['material']}", f"- **새로움·비틀기**: {a['topic']['novelty']}",
          f"- **시즌·트렌드 연결**: {a['topic']['trend_hook']}", f"- **채널 반복 요소**: {a['topic']['series']}", '',
          '## 떡상 공식', ' → '.join(a['formula']), '', '## 왜 떡상했나', bullets(a['why'], num=True), '']
    vi = a['visual']; pp = vi['people']
    L += ['## 🎥 앵글·화면 구성', '',
          f"- **사람**: 얼굴 {pp['face_pct']}% · 손 {pp['hands_pct']}% · 물체만 {pp['object_only_pct']}% — {pp['face_role']}",
          f"- **메모**: {pp['note']}",
          f"- **샷 크기 비율**: " + ' · '.join(f'{k} {val}%' for k, val in vi['sizes'].items()),
          f"- **룩(조명·색·배경)**: {vi['look']}", '',
          table(['앵글', '비율', '컷 번호', '왜'], [[x['name'], f"{x.get('pct', '')}%", ', '.join(map(str, x.get('shots', [])[:25])), x.get('why', '')] for x in vi['angles']]),
          '', '### 시그니처 샷', bullets(vi['signature_shots']), '']
    pc = a['pacing']
    L += ['## ⚡ 컷 리듬(빡빡빡)', '', pc['summary'], '',
          f"- **실제 컷** {pc['cuts_real']}개 · 평균 {pc['avg_shot_s']}초 · 중앙값 {pc['median_shot_s']}초 · 분당 {pc['cpm']}컷",
          f"- **가장 빠른 연타 구간**: {pc['fastest_run']}", f"- **가장 긴 컷**: {pc['slowest']}", f"- **배속·슬로모**: {pc['speed_ramps']}",
          f"- **리듬 해석**: {pc['rhythm_note']}", '',
          table(['구간(초)', '초당 컷', '메모'], [[f"{c.get('t0')}–{c.get('t1')}", c.get('cps'), c.get('note', '')] for c in pc['curve']]), '']
    so = a['sound']
    L += ['## 🔊 소리·ASMR', '', so['summary'], '',
          f"- **ASMR(현장음)**: {so['layers'].get('asmr', '')}", f"- **배경음악**: {so['layers'].get('bgm', '')}",
          f"- **목소리**: {so['layers'].get('voice', '')}", f"- **효과음**: {so['layers'].get('sfx', '')}",
          f"- **BGM 추정**: {so['bgm'].get('guess', '')} · 역할: {so['bgm'].get('role', '')} · 크기: {so['bgm'].get('level', '')}",
          f"- **목소리 상세**: {'있음' if so['voice'].get('present') else '없음'} · {so['voice'].get('type', '')} · {so['voice'].get('timing', '')}",
          f"- **믹스**: {so['mix']}", f"- **소리 먼저 오는 순간**: {so['sound_first']}", '', '### ASMR 타임라인',
          table(['초', '컷', '소리', '어떻게 강조'], [[x.get('t'), x.get('n'), x.get('type'), x.get('how', '')] for x in so['asmr']]), '']
    if so['sfx']:
        L += ['### 효과음 타임라인', table(['초', '컷', '효과음', '역할'], [[x.get('t'), x.get('n'), x.get('type'), x.get('role', '')] for x in so['sfx']]), '']
    ef = a['edit_fx']
    L += ['## ✂️ 편집 효과·퀄', '', ef['summary'], '',
          table(['전환', '횟수', '컷'], [[x.get('type'), x.get('count'), ', '.join(map(str, x.get('shots', [])[:20]))] for x in ef['transitions']]), '',
          table(['효과', '컷', '재현법'], [[x.get('name'), ', '.join(map(str, x.get('shots', [])[:20])), x.get('how', '')] for x in ef['effects']]), '',
          f"- **색보정 룩**: {ef['grade']}", '', '### 다른 쇼츠와 확실히 다른 점', bullets(ef['quality_diff'], num=True), '']
    cp = a['captions']
    L += ['## 🔤 자막', '', cp['summary'], '', f"- **빈도**: {cp['density']}", f"- **근거**: {cp['note']}", '']
    if cp['styles']:
        L += [table(['스타일', '규격', '용도'], [[x.get('name'), x.get('spec'), x.get('use')] for x in cp['styles']]), '']
    L += ['## 스토리 비트', table(['비트', '구간(초)', '감정', '내용'], [[b['name'], f"{b['t0']}–{b['t1']}", f"{b['e']:+.1f}", b['desc']] for b in a['beats']]), '']
    ci = a['comments_insight']
    L += ['## 💬 댓글 반응(인기 댓글 60개 기준, 의역)', '',
          table(['반응', '비율', '예(의역)'], [[x.get('theme'), x.get('share'), x.get('example_paraphrase')] for x in ci['themes']]), '',
          f"- **댓글을 부르는 장치**: {ci['what_triggers_comments']}", f"- **작성자 고정·답글 활용**: {ci['uploader_pin']}", '']
    L += [f"## 컷별 분석 ({S['n']}컷)", '각 컷 제목의 ▶ 링크는 유튜브 해당 장면(초 단위)으로 이동합니다.', '']
    for s, x in zip(cj['shots'], a['shots']):
        head = (f"### #{x['n']:02d} {s['t_in']:.2f}–{s['t_out']:.2f}s ({s['dur']:.2f}초) · {ROLE.get(x['role'], x['role'])} · "
                f"{SUBJ.get(x['subj'], x['subj'])} · {x['sz']} · {x['ang']} · {x['cam']} · {x['speed']} · {CUT.get(x['cut_type'], x['cut_type'])}")
        L += [head, f"- ▶ [{s['t_in']:.1f}초 장면 보기]({yt(v['id'], s['t_in'])})"]
        if img_rel:
            L += [f"- ![#{x['n']} 중간 프레임]({img_rel}/s{x['n']:03d}_m.jpg)"]
        L += [f"- **내용**: {x['act']}", f"- **소리**: {x['asmr']}" + (f" · **효과음**: {x['sfx']}" if x['sfx'] else ''),
              f"- **효과·전환**: {x['fx']}" + (f" · **자막 의도**: {x['cap']}" if x['cap'] else ''),
              f"- **왜 여기**: {x['why']}", f"- **재현 촬영**: {x['shoot']}", f"- **AI 프롬프트**: `{x['prompt']}`", '']
    L += ['## 재사용 편집 기법', bullets(a['tech'], num=True), '',
          '## 🧰 편집 키트', f"- 파일: `편집키트/{v['key']}/edl.csv`(컷 표) · `sfx_cues.csv`(소리 큐) · `편집레시피.md`", '',
          '### 촬영 샷 리스트', bullets(a['kit']['shoot_list']), '', '### 편집 순서', bullets(a['kit']['edit_recipe'], num=True), '',
          '### 무료 효과음 검색어', ', '.join(a['kit']['sfx_search']), '',
          '## 🐹 적용하기', f"- **그대로 가져갈 것**: {' / '.join(a['adapt']['keep'])}", f"- **바꿀 것**: {' / '.join(a['adapt']['change'])}",
          f"- **AI 동물 캐릭터 쇼츠에 옮기면**: {a['adapt']['idea_ai_shorts']}", f"- **실사 채널에 옮기면**: {a['adapt']['idea_live_action']}", '']
    return '\n'.join(L), S


# ---------- 개요·비교표 ----------
def compare_rows(items):
    rows = []
    for v, a, S in items:
        rows.append([f"[{label(v)}](#{anchor(v)})", title_short(v['title'], 26), a['fmt'] if a else '', f"{S['dur']:.0f}초",
                     S['n_real'], f"{S['avg']:.2f}", f"{S['cpm']:.0f}", S['lufs'], f"{S['sync']}/{S['chance']}", f"{S['face']:.0f}%",
                     f"{S['obj']:.0f}%", a['hook']['score'] if a else '', ' → '.join(a['formula'][:4]) + ' …' if a else ''])
    return table(['영상', '제목', '형식', '길이', '컷', '평균컷(초)', '분당컷', 'LUFS', '컷-타격음 일치/우연(%)', '얼굴', '물체만', '훅', '핵심 구조'], rows)


def anchor(v):
    return f"v-{v['key']}"


def md_ranking():
    L = ['## 선정 방법 (청담언니)', f"- 대상: 청담언니 쇼츠 탭 최근 {RK['pool_size']}개(업로드 {ymd(RK['pool_range'][0])} ~ {ymd(RK['pool_range'][1])}, 기준일 {BASE}). "
         f"긴 영상(2023~2025 모음집 8개)은 제외", f"- 종합점수: {RK['weights']}",
         '- 선정 규칙: ① 모든 섹터 1위 ② 영상 7개 이상 섹터는 2위도(점수 75 이상) ③ 나머지는 점수순, 섹터당 최대 4개로 20개 ④ 20번째와 1점 이내 동점대 포함 → 22개',
         f"- 180개 조회수 중앙값 {fnum(RK['median_views'])}", '', '### 섹터 분포(180개)',
         table(['섹터', '영상 수', '조회수 중앙값', '최고 조회수', '분석한 영상'],
               [[s['name'], s['count'], fnum(s['median_views']), fnum(s['top_views']),
                 ', '.join(f"{v['rank']}위" for v in VIDS if v['group'] == 'chengdam' and v['sector'] == k)] for k, s in RK['sectors'].items()]), '',
         '### 선정 22개', table(['순위', '점수', '섹터', '제목', '업로드', '조회수', '일평균', '댓글', '댓글/1천뷰', '링크'],
                                [[v['rank'], v['score'], SNAME[v['sector']], title_short(v['title'], 34), ymd(v['date']), fnum(v['views']),
                                  fnum(v['vpd']), fnum(v['comments']), round(v['comments'] / v['views'] * 1000, 3), yt(v['id'])]
                                 for v in VIDS if v['group'] == 'chengdam'])]
    return '\n'.join(L)


def write_kit(v, a, cj):
    d = os.path.join(OUT, '편집키트', v['key']); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'edl.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['컷', '시작초', '끝초', '길이초', '컷종류', '주인공', '크기', '앵글', '카메라', '속도', '효과전환', '역할', '자막의도', '소리', '효과음', '유튜브장면'])
        for s, x in zip(cj['shots'], a['shots']):
            w.writerow([x['n'], s['t_in'], s['t_out'], s['dur'], x['cut_type'], x['subj'], x['sz'], x['ang'], x['cam'], x['speed'], x['fx'],
                        x['role'], x['cap'], x['asmr'], x['sfx'], yt(v['id'], s['t_in'])])
    with open(os.path.join(d, 'sfx_cues.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f); w.writerow(['초', '컷', '종류', '소리', '메모'])
        cues = [(x.get('t'), x.get('n'), 'ASMR', x.get('type'), x.get('how', '')) for x in a['sound']['asmr']]
        cues += [(x.get('t'), x.get('n'), '효과음', x.get('type'), x.get('role', '')) for x in a['sound']['sfx']]
        for c in sorted(cues, key=lambda c: (c[0] if isinstance(c[0], (int, float)) else 0)):
            w.writerow(c)
    rec = [f"# 편집 레시피 — {label(v)} 「{title_short(v['title'], 50)}」", '', f"원본: {yt(v['id'])}", '',
           '## 촬영 샷 리스트', bullets(a['kit']['shoot_list']), '', '## 편집 순서', bullets(a['kit']['edit_recipe'], num=True), '',
           '## 컷 리듬 기준', f"- 평균 {a['pacing']['avg_shot_s']}초 · 분당 {a['pacing']['cpm']}컷 · 빠른 구간: {a['pacing']['fastest_run']}",
           f"- 배속: {a['pacing']['speed_ramps']}", '', '## 소리', f"- {a['sound']['mix']}", '', '## 무료 효과음 검색어', ', '.join(a['kit']['sfx_search']), '',
           '## 자막 규격', render_any(a['captions']['styles']) if a['captions']['styles'] else '- 자막 거의 없음', '']
    open(os.path.join(d, '편집레시피.md'), 'w', encoding='utf-8').write('\n'.join(rec))


# ---------- HTML ----------
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1b18;--mut:#6b655c;--card:#fff;--line:#e7e2d9;--acc:#d9480f;--acc2:#0b7285;--code:#f3f0ea}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15130f;--fg:#ece7de;--mut:#a39c90;--card:#1e1b16;--line:#35302a;--acc:#ff8c5a;--acc2:#5ec8d8;--code:#26221c}}
:root[data-theme=dark]{--bg:#15130f;--fg:#ece7de;--mut:#a39c90;--card:#1e1b16;--line:#35302a;--acc:#ff8c5a;--acc2:#5ec8d8;--code:#26221c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
header a{color:var(--fg);text-decoration:none;padding:4px 10px;border:1px solid var(--line);border-radius:999px;font-size:14px}
header a.on{background:var(--fg);color:var(--bg)}header .sp{flex:1}
button{font:inherit;font-size:13px;padding:5px 12px;border-radius:8px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--acc)}
.wrap{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;max-width:1400px;margin:0 auto;padding:16px}
nav.toc{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 80px);overflow:auto;font-size:13px;border-right:1px solid var(--line);padding-right:12px}
nav.toc a{display:block;color:var(--mut);text-decoration:none;padding:2px 0}nav.toc a.h1{color:var(--fg);font-weight:700;margin-top:8px}
main{min-width:0}h1{font-size:24px;line-height:1.3;border-bottom:2px solid var(--fg);padding-bottom:6px;margin-top:40px}
h2{font-size:19px;margin-top:30px;color:var(--acc2)}h3{font-size:15.5px;margin-top:20px}
table{border-collapse:collapse;display:block;overflow-x:auto;width:max-content;max-width:100%;font-size:13.5px;margin:10px 0}
th,td{border:1px solid var(--line);padding:5px 8px;vertical-align:top;text-align:left;min-width:3.5em;max-width:30em}
td:first-child{white-space:nowrap}th{background:var(--code);white-space:nowrap}
code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:12.5px;word-break:break-word}
a{color:var(--acc2)}img{max-width:180px;border-radius:6px;margin:2px;vertical-align:top}
section.video{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:4px 20px 20px;margin:24px 0}
.bar{display:flex;gap:8px;margin:10px 0}.note{color:var(--mut);font-size:13px}
@media (max-width:860px){.wrap{grid-template-columns:1fr}nav.toc{display:none}body{font-size:14.5px}.wrap{padding:12px 16px}}
"""
JS = """
function cp(id,btn){const t=document.getElementById(id).value;navigator.clipboard.writeText(t).then(()=>{const o=btn.textContent;btn.textContent='복사됨 ✓';setTimeout(()=>btn.textContent=o,1500)}).catch(()=>{const ta=document.getElementById(id);ta.style.display='block';ta.select();document.execCommand('copy');ta.style.display='none'})}
document.getElementById('theme').onclick=()=>{const r=document.documentElement;r.dataset.theme=(r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches))?'light':'dark'};
"""
PAGES = [('index.html', '홈·개요'), ('청담언니.html', '청담언니 22개'), ('개별영상.html', '개별 영상 8개'), ('플레이북.html', '플레이북(사전)')]


def page(fn, title, blocks, all_md):
    """blocks: [(md, section_id or None, copy_md or None)]"""
    body, toc = [], []
    ext = ['tables', 'toc', 'sane_lists']
    for i, (md, sid, cmd) in enumerate(blocks):
        h = mdlib.markdown(md, extensions=ext)
        for m in re.finditer(r'<h([12]) id="([^"]+)">(.*?)</h\1>', h):
            toc.append(f'<a class="h{m.group(1)}" href="#{m.group(2)}">{re.sub("<[^>]+>", "", m.group(3))}</a>')
        if cmd:
            tid = f'md{i}'
            h = (f'<section class="video" id="{sid}"><div class="bar"><button onclick="cp(\'{tid}\',this)">📋 이 영상 복사</button></div>'
                 f'<textarea id="{tid}" style="display:none">{html.escape(cmd)}</textarea>{h}</section>')
        body.append(h)
    nav = ''.join(f'<a href="{p}" class="{"on" if p == fn else ""}">{t}</a>' for p, t in PAGES)
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>
<header>{nav}<a href="전체분석.txt">전체 txt</a><span class="sp"></span><button onclick="cp('allmd',this)">📋 이 페이지 전체 복사</button><button class="ghost" id="theme">🌓</button></header>
<textarea id="allmd" style="display:none">{html.escape(all_md)}</textarea>
<div class="wrap"><nav class="toc">{''.join(toc)}</nav><main>{''.join(body)}</main></div><script>{JS}</script></body></html>"""
    open(os.path.join(OUT, fn), 'w', encoding='utf-8').write(doc)


def main():
    os.makedirs(OUT, exist_ok=True)
    items = {'chengdam': [], 'single': []}; video_md = {}
    for v in VIDS:
        d = os.path.join('videos', v['key']); a = load(os.path.join(d, 'analysis.json'))
        if not a:
            print('분석 없음(건너뜀):', v['key']); continue
        cj = load(os.path.join(d, 'cuts.json')); au = load(os.path.join(d, 'audio.json'), {}); fc = load(os.path.join(d, 'faces.json'), {})
        img_rel = None
        if PRIVATE:
            dst = os.path.join(OUT, '캡처', v['key']); os.makedirs(dst, exist_ok=True)
            for p in glob.glob(os.path.join(d, 'shots', '*_m.jpg')):  # 용량 절약: 컷 중간 프레임만
                shutil.copy2(p, dst)
            for p in ['hook_0-3s.jpg', 'ending_last3s.jpg', 'spectrogram.png']:
                if os.path.exists(os.path.join(d, p)):
                    shutil.copy2(os.path.join(d, p), dst)
            img_rel = f'캡처/{v["key"]}'
        md, S = md_video(v, a, cj, au, fc, img_rel)
        if PRIVATE:
            md = md.replace('## 한 줄 요약', f'![처음 3초]({img_rel}/hook_0-3s.jpg) ![마지막 3초]({img_rel}/ending_last3s.jpg)\n\n## 한 줄 요약', 1)
        video_md[v['key']] = md; items[v['group']].append((v, a, S))
        write_kit(v, a, cj)
        dd = os.path.join(OUT, '분석데이터'); os.makedirs(dd, exist_ok=True)
        json.dump(a, open(os.path.join(dd, f"{v['key']}_분석.json"), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        json.dump({k: cj[k] for k in ('fps', 'frames', 'duration', 'size', 'threshold', 'shots')}, open(os.path.join(dd, f"{v['key']}_컷타이밍.json"), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        json.dump(au, open(os.path.join(dd, f"{v['key']}_소리특징.json"), 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(fc, open(os.path.join(dd, f"{v['key']}_얼굴검출.json"), 'w', encoding='utf-8'), ensure_ascii=False)
        open(os.path.join(OUT, f"{fname(v)}.txt"), 'w', encoding='utf-8').write(md)
    sc = load('data/synth_channel.json', {}); ss = load('data/synth_singles.json', {})
    p1 = load('data/synth_playbook_hook_visual.json', {}); p2 = load('data/synth_playbook_edit_sound.json', {})
    # 개요 md
    intro = ['# 청담언니 + 개별 쇼츠 8개 — 컷 단위 분석', '',
             f'청담언니(구독 {fnum(VIDS[0]["subs"])}) 최근 쇼츠 180개를 섹터로 나누고 조회수·댓글·최신성으로 22개를 골라, 사용자가 준 개별 쇼츠 8개와 함께 **컷 단위로 분해**했습니다(기준일 {BASE}).',
             '초점: ① 소재·어그로(훅) ② 앵글 ③ 빠른 컷(빡빡빡) ④ 소리·ASMR ⑤ 편집 효과·퀄 ⑥ 사람 얼굴 vs 물체만.',
             '원본 자막·대사·댓글은 옮기지 않고 의도만 요약했습니다(댓글 예시는 의역). 영상 캡처 사진은 공개판에 넣지 않고, 컷마다 유튜브 해당 장면 링크를 달았습니다.', '']
    ch_items = items['chengdam']; sg_items = items['single']
    ov = intro + ['## 한눈에 보기 — 청담언니 22개 비교표', compare_rows(ch_items), '', '## 한눈에 보기 — 개별 영상 8개 비교표', compare_rows(sg_items), '',
                  md_ranking(), '']
    if sc:
        ov += ['# 청담언니 채널 공식·섹터 분석', render_any(sc, 2), '']
    ov_md = '\n'.join(ov)
    singles_intro = ['# 개별 영상 8개 종합', '각 영상은 채널 전체가 아니라 **그 영상 하나만** 분석했습니다.', '', compare_rows(sg_items), '']
    if ss:
        singles_intro += [render_any(ss, 2)]
    sg_md = '\n'.join(singles_intro)
    pb_md = '\n'.join(['# 플레이북 — 30개 영상에서 뽑은 사전', '청담언니 22개 + 개별 8개의 컷 분석을 합쳐 만든 훅·앵글·리듬·ASMR·효과 사전입니다.', '',
                       render_any(p1, 2) if p1 else '(준비 중)', '', render_any(p2, 2) if p2 else ''])
    open(os.path.join(OUT, '개요.txt'), 'w', encoding='utf-8').write(ov_md)
    open(os.path.join(OUT, '개별영상_종합.txt'), 'w', encoding='utf-8').write(sg_md)
    open(os.path.join(OUT, '플레이북.txt'), 'w', encoding='utf-8').write(pb_md)
    ch_md = '\n\n---\n\n'.join(video_md[v['key']] for v, _, _ in ch_items)
    s_md = '\n\n---\n\n'.join(video_md[v['key']] for v, _, _ in sg_items)
    full = '\n\n---\n\n'.join([ov_md, pb_md, sg_md, ch_md, s_md])
    for ext in ('md', 'txt'):
        open(os.path.join(OUT, f'전체분석.{ext}'), 'w', encoding='utf-8').write(full)
    page('index.html', '청담언니·개별 쇼츠 컷 분석', [(ov_md, None, None)], ov_md)
    page('청담언니.html', '청담언니 22개 컷 분석', [('# 청담언니 22개 — 영상별 컷 분석\n\n' + compare_rows(ch_items), None, None)] +
         [(video_md[v['key']], anchor(v), video_md[v['key']]) for v, _, _ in ch_items], ch_md)
    page('개별영상.html', '개별 쇼츠 8개 컷 분석', [(sg_md, None, None)] + [(video_md[v['key']], anchor(v), video_md[v['key']]) for v, _, _ in sg_items],
         sg_md + '\n\n' + s_md)
    page('플레이북.html', '쇼츠 플레이북(사전)', [(pb_md, None, None)], pb_md)
    for p in ['data/ranking.json', 'data/ranking_pool.csv', 'data/videos.json'] + glob.glob('data/synth_*.json'):
        shutil.copy2(p, os.path.join(OUT, '분석데이터'))
    if not PRIVATE:
        td = os.path.join(OUT, '도구'); os.makedirs(td, exist_ok=True)
        for p in glob.glob('tools/*.py') + ['tools/AGENT_BRIEF.md']:
            shutil.copy2(p, td)
    if not PRIVATE:
        write_readme(ch_items, sg_items)
        open(os.path.join(OUT, '.nojekyll'), 'w').close()
    print(f"완료: 청담 {len(ch_items)}개 · 개별 {len(sg_items)}개 · 컷 {sum(S['n'] for _, _, S in ch_items + sg_items)}개 → {OUT}")


PAGES_URL = 'https://geben147-create.github.io/chengdam-shorts-analysis/'
RAW_URL = 'https://raw.githubusercontent.com/geben147-create/chengdam-shorts-analysis/main/'


def link(name, base=PAGES_URL):
    from urllib.parse import quote
    return base + quote(name)


def write_readme(ch_items, sg_items):
    n_cuts = sum(S['n'] for _, _, S in ch_items + sg_items)
    L = ['# 청담언니 + 개별 쇼츠 8개 — 컷 단위 분석', '',
         f'청담언니(구독 935만) 최근 쇼츠 180개 → 섹터 9개로 나누고 조회수·댓글·최신성 종합점수로 **{len(ch_items)}개 선정** + 사용자가 고른 **개별 쇼츠 {len(sg_items)}개** — 총 **{n_cuts}컷**을 하나씩 분해했습니다(기준일 {BASE}).',
         '', '초점: ① 소재·어그로(훅) ② 앵글 ③ 빠른 컷(빡빡빡) ④ 소리·ASMR ⑤ 편집 효과·퀄 ⑥ 사람 얼굴 vs 물체만', '',
         '## 바로 열기', '| 무엇 | 링크 |', '|---|---|',
         f'| 🏠 홈 — 비교표·선정 방법·채널 공식·섹터 분석 | [{PAGES_URL}]({PAGES_URL}) |',
         f"| 🧊 청담언니 {len(ch_items)}개 영상별 컷 분석 (📋 영상별 복사) | [청담언니.html]({link('청담언니.html')}) |",
         f"| 🎬 개별 쇼츠 {len(sg_items)}개 (각 영상 하나만 분석) | [개별영상.html]({link('개별영상.html')}) |",
         f"| 📚 플레이북 — 훅·앵글·리듬·ASMR·효과 사전 | [플레이북.html]({link('플레이북.html')}) |",
         f"| 전체 텍스트 (AI가 바로 읽는 txt) | [전체분석.txt]({link('전체분석.txt')}) |",
         f"| 나눈 텍스트 | [개요.txt]({link('개요.txt')}) · [플레이북.txt]({link('플레이북.txt')}) · [개별영상_종합.txt]({link('개별영상_종합.txt')}) |",
         f"| 원문 그대로(raw) | [전체분석.md]({link('전체분석.md', RAW_URL)}) |", '',
         '## 영상별 텍스트', '| 영상 | 제목 | txt | 원본 |', '|---|---|---|---|']
    for v, a, S in ch_items + sg_items:
        L.append(f"| {label(v)} | {esc_pipe(title_short(v['title'], 34))} | [{fname(v)}.txt]({link(fname(v) + '.txt')}) | [유튜브]({yt(v['id'])}) |")
    L += ['', '## 영상 1개 분석에 들어 있는 것',
          '- 한 줄 요약 · 🎣 소재·어그로(제목 장치·첫 프레임·0~1초·0~3초·약속→회수·재훅·루프, 훅 점수) · 떡상 공식 · 왜 떡상했나',
          '- 🎥 앵글·화면(얼굴/손/물체만 비율, 앵글별 컷 번호, 샷 크기, 시그니처 샷) · ⚡ 컷 리듬(분당 컷·연타 구간·배속·5초 단위 곡선)',
          '- 🔊 소리·ASMR(LUFS·타격음 밀도·컷-타격음 일치율, ASMR/효과음 타임라인, BGM 추정) · ✂️ 편집 효과·퀄(전환·효과·색·다른 쇼츠와 다른 점)',
          '- 🔤 자막 규격 · 스토리 비트 · 💬 댓글 반응(의역) · **컷별 분석**(컷마다 역할·주인공·크기·앵글·카메라·속도·소리·효과·왜·재현 촬영·AI 프롬프트·유튜브 장면 링크)',
          '- 🧰 편집 키트(`편집키트/<키>/edl.csv` 컷 표 · `sfx_cues.csv` 소리 큐 · `편집레시피.md`) · 🐹 적용하기(AI 동물 쇼츠·실사 채널)', '',
          '## 폴더 구성',
          '- `index.html`·`청담언니.html`·`개별영상.html`·`플레이북.html` — 웹 페이지(📋 복사 버튼)',
          '- `전체분석.md/.txt`, `개요.txt`, `청담언니_NN위.txt`, `개별영상_N.txt`, `플레이북.txt`, `개별영상_종합.txt`',
          '- `분석데이터/` — 영상별 컷 분석 JSON(`<키>_분석.json`)·컷 타이밍·소리 특징·얼굴 검출 참고값, 순위(`ranking.json`, `ranking_pool.csv` = 180개 전체), 종합(`synth_*.json`)',
          '- `편집키트/<키>/` — edl.csv · sfx_cues.csv · 편집레시피.md', '- `도구/` — 전처리·검사·사이트 생성 파이썬, 분석 지침서(AGENT_BRIEF.md)', '- `작업기록.md`', '',
          '## 공개하지 않은 것',
          '원본 영상·캡처 사진·자막/대사 원문·댓글 원문은 각 채널 저작물이라 올리지 않았습니다. 분석 문장은 의도만 요약했고 댓글은 의역했습니다. 대신 컷마다 유튜브 해당 장면(초) 링크를 달았습니다.', '']
    open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write('\n'.join(L))


if __name__ == '__main__':
    main()
