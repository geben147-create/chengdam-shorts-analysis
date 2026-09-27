"""analysis.json 자동 검사: 컷 수·필수 키·허용 값·숫자 범위·개수·원문 복사(연속 일치).
사용: python tools/validate.py <키> [키...]   (키 없으면 전체) — 문제 없으면 마지막 줄 OK"""
import sys, os, json, re

TOP = {
    'key': str, 'group': str, 'rank': int, 'id': str, 'fmt': str, 'sector': str, 'logline': str, 'why': list, 'formula': list,
    'hook': dict, 'topic': dict, 'visual': dict, 'pacing': dict, 'sound': dict, 'edit_fx': dict, 'captions': dict,
    'beats': list, 'comments_insight': dict, 'shots': list, 'tech': list, 'adapt': dict, 'kit': dict,
}
NESTED = {
    'hook': ['title_hook', 'first_frame', 'first_1s', 'first_3s', 'text_hook', 'aggro_types', 'promise_payoff',
             'retention_devices', 'ending_loop', 'score', 'score_note'],
    'topic': ['material', 'novelty', 'trend_hook', 'series'],
    'visual': ['people', 'angles', 'sizes', 'look', 'signature_shots'],
    'pacing': ['summary', 'cuts_real', 'avg_shot_s', 'median_shot_s', 'cpm', 'fastest_run', 'slowest', 'speed_ramps',
               'rhythm_note', 'curve'],
    'sound': ['summary', 'layers', 'asmr', 'sfx', 'bgm', 'voice', 'mix', 'sound_first'],
    'edit_fx': ['summary', 'transitions', 'effects', 'grade', 'quality_diff'],
    'captions': ['summary', 'styles', 'density', 'note'],
    'comments_insight': ['themes', 'what_triggers_comments', 'uploader_pin'],
    'adapt': ['keep', 'change', 'idea_ai_shorts', 'idea_live_action'],
    'kit': ['shoot_list', 'edit_recipe', 'sfx_search'],
}
SHOT_KEYS = ['n', 'cut_type', 'subj', 'sz', 'ang', 'cam', 'speed', 'act', 'asmr', 'sfx', 'cap', 'fx', 'role', 'why', 'shoot', 'prompt']
MAY_EMPTY = {'sfx', 'cap'}
ENUM = {
    'cut_type': {'hard', 'jump', 'match', 'whip', 'dissolve', 'flash', 'false'},
    'subj': {'face', 'face_hands', 'hands', 'object', 'person', 'text', 'mixed'},
    'sz': {'ECU', 'CU', 'MCU', 'MS', 'WS', 'EWS', 'insert'},
    'role': {'hook', 'setup', 'build', 'tension', 'reveal', 'payoff', 'reaction', 'rehook', 'cta', 'loop', 'broll'},
}
ANG_WORDS = ['탑다운', '하이앵글', '아이레벨', '로우앵글', '매크로', '측면', '정면', 'POV', '셀카', '부감']
SECTORS = {'drink', 'ice', 'dessert', 'cook', 'ng', 'asmr', 'mass', 'ad', 'life'}
COUNTS = {  # (경로, 최소, 최대, 오류여부)
    'why': (5, 7, True), 'formula': (8, 12, True), 'tech': (10, 40, True), 'beats': (3, 20, True),
    'hook.aggro_types': (1, 8, True), 'hook.retention_devices': (1, 10, True),
    'visual.angles': (1, 12, True), 'visual.signature_shots': (2, 8, True),
    'sound.asmr': (3, 25, True), 'sound.sfx': (0, 25, True), 'edit_fx.quality_diff': (3, 5, True),
    'edit_fx.transitions': (1, 12, True), 'edit_fx.effects': (1, 20, True), 'captions.styles': (0, 10, True),
    'comments_insight.themes': (3, 6, True), 'kit.edit_recipe': (6, 10, True), 'kit.sfx_search': (8, 15, True),
    'kit.shoot_list': (3, 30, True), 'adapt.keep': (2, 10, True), 'adapt.change': (2, 10, True), 'pacing.curve': (2, 30, True),
}


def norm(s):
    return re.sub(r'[^0-9A-Za-z가-힣]', '', s or '').lower()


def get(a, path):
    cur = a
    for p in path.split('.'):
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def strings(o, path=''):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from strings(v, f'{path}.{k}' if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from strings(v, f'{path}[{i}]')


def source_grams(d):
    texts = []
    try:
        texts += [s['text'] for s in json.load(open(os.path.join(d, 'whisper.json'), encoding='utf-8'))['segments']
                  if s.get('no_speech_prob', 0) < 0.8]
    except (OSError, KeyError, ValueError):
        pass
    try:
        for s in json.load(open(os.path.join(d, 'ocr_palette.json'), encoding='utf-8'))['shots']:
            texts.append(''.join(b['text'] for b in s['text_boxes']))
    except (OSError, KeyError, ValueError):
        pass
    try:
        texts += [c['text'] for c in json.load(open(os.path.join(d, 'comments.json'), encoding='utf-8'))['comments']]
    except (OSError, KeyError, ValueError):
        pass
    grams = set()
    for t in texts:
        n = norm(t)
        for i in range(len(n) - 11):
            grams.add(n[i:i + 12])
    return grams


def check(key):
    d = os.path.join('videos', key); errs, warns = [], []
    p = os.path.join(d, 'analysis.json')
    try:
        a = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return [f'analysis.json 읽기 실패: {e}'], []
    cj = json.load(open(os.path.join(d, 'cuts.json'), encoding='utf-8'))
    N = len(cj['shots'])
    for k, t in TOP.items():
        if k not in a:
            errs.append(f'최상위 키 없음: {k}')
        elif not isinstance(a[k], t):
            errs.append(f'{k} 타입이 {t.__name__} 아님')
    if errs:
        return errs, warns
    if a['key'] != key:
        errs.append(f"key 값 {a['key']} ≠ {key}")
    if key.startswith('c') and a['sector'] not in SECTORS:
        errs.append(f"sector 는 {sorted(SECTORS)} 중 하나")
    for k, subs in NESTED.items():
        for s in subs:
            if s not in a[k]:
                errs.append(f'{k}.{s} 없음')
    for path, (lo, hi, hard) in COUNTS.items():
        v = get(a, path)
        if not isinstance(v, list):
            errs.append(f'{path} 가 리스트 아님'); continue
        if not lo <= len(v) <= hi:
            (errs if hard else warns).append(f'{path} 개수 {len(v)} (허용 {lo}~{hi})')
    sc = get(a, 'hook.score')
    if not (isinstance(sc, int) and 1 <= sc <= 10):
        errs.append('hook.score 는 1~10 정수')
    for b in a['beats']:
        if not all(x in b for x in ('name', 't0', 't1', 'e', 'desc')):
            errs.append(f'beats 원소 키 부족: {b}'); break
        if not (isinstance(b['e'], (int, float)) and -1 <= b['e'] <= 1):
            errs.append(f"beats e 범위(-1~1) 벗어남: {b['name']}")
    for path in ['visual.people.face_pct', 'visual.people.hands_pct', 'visual.people.object_only_pct', 'pacing.cuts_real',
                 'pacing.avg_shot_s', 'pacing.median_shot_s', 'pacing.cpm']:
        v = get(a, path)
        if not isinstance(v, (int, float)):
            errs.append(f'{path} 는 숫자')
    for x in a['sound']['asmr'] + a['sound']['sfx']:
        if not all(k in x for k in ('t', 'n', 'type')):
            errs.append(f'sound asmr/sfx 원소 키 부족(t,n,type): {x}'); break
    # 컷
    shots = a['shots']
    if [s.get('n') for s in shots] != list(range(1, N + 1)):
        errs.append(f'shots 번호가 1..{N} 과 다름 (현재 {len(shots)}개) — cuts.json 컷 수 {N} 그대로')
    for s in shots:
        for k in SHOT_KEYS:
            if k not in s:
                errs.append(f"#{s.get('n')} {k} 없음"); continue
            if k != 'n' and k not in MAY_EMPTY and not str(s[k]).strip():
                errs.append(f"#{s.get('n')} {k} 비어 있음")
        for k, allowed in ENUM.items():
            if k in s and s[k] not in allowed:
                errs.append(f"#{s.get('n')} {k}={s[k]!r} (허용: {'|'.join(sorted(allowed))})")
        if 'ang' in s and not any(w in s['ang'] for w in ANG_WORDS):
            errs.append(f"#{s.get('n')} ang={s['ang']!r} 에 표준 앵글 단어 없음({'|'.join(ANG_WORDS)})")
        pr = s.get('prompt', '')
        if pr and len(re.findall('[가-힣]', pr)) > 0.05 * len(pr):
            errs.append(f"#{s.get('n')} prompt 는 영어로")
    real = sum(1 for s in shots if s.get('cut_type') != 'false')
    if isinstance(get(a, 'pacing.cuts_real'), int) and abs(a['pacing']['cuts_real'] - real) > 0:
        errs.append(f"pacing.cuts_real={a['pacing']['cuts_real']} ≠ false 제외 컷 수 {real}")
    # 원문 복사 검사(정규화 후 12자 연속 일치)
    grams = source_grams(d); hits = []
    for path, s in strings(a):
        if path.startswith('id') or path.endswith('.prompt') or path.startswith('kit.sfx_search'):
            continue
        n = norm(s)
        for i in range(len(n) - 11):
            g = n[i:i + 12]
            if g in grams and re.search('[가-힣]', g):
                hits.append(f'{path}: …{g}…'); break
    if hits:
        errs.append('원문(자막·대사·댓글)과 12자 이상 연속 일치 — 의도 요약/의역으로 바꾸기: ' + ' | '.join(hits[:8]))
    return errs, warns


if __name__ == '__main__':
    keys = sys.argv[1:] or [v['key'] for v in json.load(open('data/videos.json', encoding='utf-8'))]
    bad = 0
    for k in keys:
        e, w = check(k)
        for x in w:
            print(f'[{k}] 경고: {x}')
        for x in e:
            print(f'[{k}] 오류: {x}')
        bad += bool(e)
        if not e:
            print(f'[{k}] 통과')
    print('OK' if not bad else f'FAIL {bad}개 영상')
