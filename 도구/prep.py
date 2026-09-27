"""영상 전처리(결정적 계산만): 다운로드 → 컷 검출 → 샷 캡처·콘택트시트 → 훅/엔딩 시트 → 소리 특징 → 얼굴 → (별도 프로세스) 받아쓰기 / OCR → 댓글.
사용: python tools/prep.py <단계> [키...]   단계 = download|cuts|audio|faces|whisper|ocr|comments
키 생략 시 data/videos.json 전체"""
import sys, os, json, subprocess, wave, glob
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import numpy as np

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          stdin=subprocess.DEVNULL, creationflags=FLAGS, timeout=timeout)


VIDS = json.load(open('data/videos.json', encoding='utf-8'))


def vdir(v):
    return os.path.join('videos', v['key'])


# ---------- 1. 다운로드 ----------
def download(v):
    d = vdir(v); os.makedirs(d, exist_ok=True)
    if os.path.exists(os.path.join(d, 'src.mp4')):
        return v['key'], 'skip'
    r = run(['yt-dlp', '-q', '--no-warnings', '-f', 'bv*[height<=1280][ext=mp4]+ba[ext=m4a]/b[height<=1280][ext=mp4]/b',
             '--merge-output-format', 'mp4', '--write-thumbnail', '--convert-thumbnails', 'jpg',
             '-o', os.path.join(d, 'src.%(ext)s'), f"https://www.youtube.com/watch?v={v['id']}"])
    return v['key'], ('ok' if os.path.exists(os.path.join(d, 'src.mp4')) else 'FAIL ' + r.stderr[-300:])


# ---------- 2. 컷 검출 + 캡처 + 시트 ----------
def active_box(src):
    """제목 바·고정 틀(템플릿)이 있는 재편집 쇼츠 대응: 시간에 따라 실제로 변하는 영역만 찾아 컷 검출에 쓴다."""
    import cv2
    cap = cv2.VideoCapture(src); W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sw, sh = (90, 160) if H0 > W0 else (160, 90)
    stack, fi = [], 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if fi % 3 == 0:
            stack.append(cv2.cvtColor(cv2.resize(fr, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))
        fi += 1
    cap.release()
    sd = np.std(np.array(stack, dtype=np.float32), axis=0)
    act = sd > 12
    rows = np.where(act.mean(axis=1) > 0.2)[0]; cols = np.where(act.mean(axis=0) > 0.2)[0]
    if len(rows) < 5 or len(cols) < 5:
        return None
    y0, y1, x0, x1 = rows.min() / sh, (rows.max() + 1) / sh, cols.min() / sw, (cols.max() + 1) / sw
    if (y1 - y0) * (x1 - x0) > 0.85:
        return None
    return [round(float(x0), 3), round(float(y0), 3), round(float(x1), 3), round(float(y1), 3)]


def detect(src, box=None):
    import cv2
    cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS)
    W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sw, sh = (180, 320) if H0 > W0 else (320, 180)
    hist_d, mad, bright, sat, prev_h, prev_g = [], [], [], [], None, None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if box:
            x0, y0, x1, y1 = int(box[0] * W0), int(box[1] * H0), int(box[2] * W0), int(box[3] * H0)
            fr = fr[y0:y1, x0:x1]
        small = cv2.resize(fr, (sw, sh), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256]); cv2.normalize(h, h)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hist_d.append(0.0 if prev_h is None else float(cv2.compareHist(prev_h, h, cv2.HISTCMP_BHATTACHARYYA)))
        mad.append(0.0 if prev_g is None else float(np.mean(np.abs(g - prev_g))))
        bright.append(float(g.mean())); sat.append(float(hsv[..., 1].mean()))
        prev_h, prev_g = h, g
    cap.release()
    return fps, W0, H0, np.array(hist_d), np.array(mad), bright, sat


def cuts(v):
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    d = vdir(v); src = os.path.join(d, 'src.mp4')
    box = active_box(src) if v['group'] == 'single' else None
    fps, W0, H0, H, M, bright, sat = detect(src, box)
    vertical = H0 > W0; n = len(H)
    score = H / (H.mean() + 1e-6) * 0.5 + M / (M.mean() + 1e-6) * 0.5
    thr = max(float(np.percentile(score, 90)) * 2.2, 4.0)
    mingap = max(3, int(round(fps * 0.1)))  # 빠른 편집 대응: 최소 0.1초(3프레임)
    cut_f = []
    for i in range(1, n):
        win = score[max(1, i - 3): i + 4]
        if score[i] >= thr and score[i] == win.max() and H[i] > 0.15:
            if not cut_f or i - cut_f[-1] >= mingap:
                cut_f.append(i)
    if v['group'] == 'single':  # 재편집 쇼츠의 점프컷(같은 구도·시간 건너뜀) 보강 — 과검출은 분석가가 cut_type=false 로 표시
        thr2 = max(0.9 * float(np.percentile(score, 99)), 2.8)
        for i in range(1, n):
            win = score[max(1, i - 3): i + 4]
            if score[i] >= thr2 and score[i] == win.max() and H[i] > 0.08 and M[i] > 10 and all(abs(i - j) >= mingap for j in cut_f):
                cut_f.append(i)
        cut_f.sort()
    bounds = [0] + cut_f + [n]
    shots = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        shots.append({'idx': k + 1, 'f_in': a, 'f_out': b - 1, 't_in': round(a / fps, 3), 't_out': round(b / fps, 3),
                      'dur': round((b - a) / fps, 3), 'cut_score': round(float(score[a]), 2) if a else None,
                      'bright_mean': round(float(np.mean(bright[a:b])), 1), 'sat_mean': round(float(np.mean(sat[a:b])), 1),
                      'motion_mean': round(float(np.mean(M[a + 1:b])) if b - a > 1 else 0, 2)})
    json.dump({'fps': fps, 'frames': n, 'duration': round(n / fps, 3), 'size': [W0, H0], 'threshold': round(thr, 2),
               'active_box': box, 'active_box_note': '제목 바 등 고정 틀을 빼고 실제로 변하는 영역(x0,y0,x1,y1 비율)만으로 컷 검출' if box else None,
               'cuts_f': cut_f, 'shots': shots,
               'metrics': {'hist': [round(float(x), 4) for x in H], 'mad': [round(float(x), 3) for x in M],
                           'bright': [round(x, 1) for x in bright], 'sat': [round(x, 1) for x in sat],
                           'score': [round(float(x), 3) for x in score]}},
              open(os.path.join(d, 'cuts.json'), 'w', encoding='utf-8'), indent=0)
    fw, fh = (360, 640) if vertical else (640, 360)
    os.makedirs(os.path.join(d, 'shots'), exist_ok=True)
    cap = cv2.VideoCapture(src)

    def grab(fi):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(fi, n - 1))); ok, fr = cap.read()
        if not ok:
            return Image.new('RGB', (fw, fh))
        return Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)).resize((fw, fh), Image.LANCZOS)

    for s in shots:
        a, b = s['f_in'], s['f_out']
        for tag, fi in {'a': min(a + 1, b), 'm': (a + b) // 2, 'z': max(b - 1, a)}.items():
            grab(fi).save(os.path.join(d, 'shots', f"s{s['idx']:03d}_{tag}.jpg"), quality=85)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/malgunbd.ttf', 20)
    except OSError:
        font = ImageFont.load_default()
    TW, TH = (220, 391) if vertical else (400, 225)
    LH = 28; PER = 4 if vertical else 6
    os.makedirs(os.path.join(d, 'sheets'), exist_ok=True)
    for old in glob.glob(os.path.join(d, 'sheets', '*.jpg')):
        os.remove(old)
    for page in range(0, len(shots), PER):
        grp = shots[page:page + PER]
        sheet = Image.new('RGB', (TW * 3 + 8, len(grp) * (TH + LH)), (18, 18, 18)); dr = ImageDraw.Draw(sheet)
        for r, s in enumerate(grp):
            y = r * (TH + LH)
            dr.text((6, y + 3), f"#{s['idx']:02d}  {s['t_in']:.2f}→{s['t_out']:.2f}s ({s['dur']:.2f}s)  [시작|중간|끝]",
                    fill=(255, 220, 0), font=font)
            for c, tag in enumerate('amz'):
                im = Image.open(os.path.join(d, 'shots', f"s{s['idx']:03d}_{tag}.jpg")).resize((TW - 4, TH - 4))
                sheet.paste(im, (c * TW + 4, y + LH + 2))
        sheet.save(os.path.join(d, 'sheets', f"sheet_{page // PER + 1:02d}.jpg"), quality=84)

    def strip(t0, name):  # 0.2초 간격 15장(3초), 5×3
        cw, ch = (216, 384) if vertical else (384, 216)
        sheet = Image.new('RGB', (cw * 5, (ch + 26) * 3), (18, 18, 18)); dr = ImageDraw.Draw(sheet)
        for i in range(15):
            t = t0 + i * 0.2; fi = int(round(t * fps))
            if fi >= n:
                break
            im = grab(fi).resize((cw - 4, ch - 4)); x, y = (i % 5) * cw, (i // 5) * (ch + 26)
            dr.text((x + 4, y + 2), f"{t:.1f}s", fill=(255, 220, 0), font=font); sheet.paste(im, (x + 2, y + 26))
        sheet.save(os.path.join(d, f'{name}.jpg'), quality=84)

    strip(0.0, 'hook_0-3s'); strip(max(0.0, n / fps - 3.0), 'ending_last3s')
    cap.release()
    return v['key'], f"{W0}x{H0} fps={fps:.2f} dur={n / fps:.1f}s shots={len(shots)} thr={thr:.2f}"


def timeline(v):
    """컷 검출과 무관하게 1초 간격 프레임 시트(5×4=20장/시트) — 긴 컷 안의 동작·자막 변화 확인용"""
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    d = vdir(v); cap = cv2.VideoCapture(os.path.join(d, 'src.mp4')); fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cw, ch = (216, 384) if H0 > W0 else (384, 216)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/malgunbd.ttf', 20)
    except OSError:
        font = ImageFont.load_default()
    ts = [t + 0.5 for t in range(int(n / fps))]
    for old in glob.glob(os.path.join(d, 'timeline_*.jpg')):
        os.remove(old)
    for page in range(0, len(ts), 20):
        grp = ts[page:page + 20]; rows = (len(grp) + 4) // 5
        sheet = Image.new('RGB', (cw * 5, (ch + 26) * rows), (18, 18, 18)); dr = ImageDraw.Draw(sheet)
        for i, t in enumerate(grp):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps)); ok, fr = cap.read()
            if not ok:
                continue
            im = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)).resize((cw - 4, ch - 4)); x, y = (i % 5) * cw, (i // 5) * (ch + 26)
            dr.text((x + 4, y + 2), f"{t:.1f}s", fill=(120, 220, 255), font=font); sheet.paste(im, (x + 2, y + 26))
        sheet.save(os.path.join(d, f'timeline_{page // 20 + 1:02d}.jpg'), quality=82)
    cap.release()
    return v['key'], f'{len(ts)} frames'


# ---------- 3. 소리 특징 ----------
def load_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return sr, x


def loudness(src):
    r = run(['ffmpeg', '-v', 'info', '-i', src, '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'])
    tail = r.stderr[r.stderr.rfind('Summary:'):]; lo = {}
    for key, tag in [('I_LUFS', 'I:'), ('LRA_LU', 'LRA:'), ('TruePeak_dBFS', 'Peak:')]:
        pos = tail.find(tag)
        if pos >= 0:
            try:
                lo[key] = float(tail[pos + len(tag):].split()[0])
            except ValueError:
                pass
    return lo


def audio(v):
    from scipy.signal import find_peaks
    d = vdir(v); src = os.path.join(d, 'src.mp4'); wav = os.path.join(d, 'audio_22k.wav')
    run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-vn', '-ac', '1', '-ar', '22050', wav])
    run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-lavfi',
         'showspectrumpic=s=1600x360:legend=0:color=intensity:scale=log:fscale=log', os.path.join(d, 'spectrogram.png')])
    sr, x = load_wav(wav)
    hop, win = 512, 2048
    frames = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(frames)[:, None]
    seg = x[idx] * np.hanning(win)[None, :]; mag = np.abs(np.fft.rfft(seg, axis=1))
    t = (np.arange(frames) * hop + win / 2) / sr
    rms_db = 20 * np.log10(np.sqrt((x[idx] ** 2).mean(axis=1)) + 1e-9)
    flux = np.maximum(np.diff(np.log1p(mag), axis=0), 0).sum(axis=1); flux = np.concatenate([[0], flux])
    flux_n = (flux - flux.mean()) / (flux.std() + 1e-9)
    peaks, _ = find_peaks(flux_n, height=1.5, distance=int(0.09 * sr / hop)); onsets = t[peaks]
    env = flux_n - flux_n.mean(); ac = np.correlate(env, env, 'full')[len(env) - 1:]
    lag_min, lag_max = int(60 / 180 * sr / hop), int(60 / 60 * sr / hop)
    lag = lag_min + int(np.argmax(ac[lag_min:lag_max])); bpm = 60 * sr / hop / lag
    freqs = np.fft.rfftfreq(win, 1 / sr)
    centroid = (mag * freqs[None, :]).sum(axis=1) / (mag.sum(axis=1) + 1e-9)
    power = mag ** 2; hf = power[:, freqs >= 4000].sum(axis=1) / (power.sum(axis=1) + 1e-9)
    silence = rms_db < -45
    cj = json.load(open(os.path.join(d, 'cuts.json'), encoding='utf-8')); shots = cj['shots']; dur = cj['duration']
    cuts_t = [s['t_in'] for s in shots[1:]]
    near = [float(np.min(np.abs(onsets - c))) if len(onsets) else 9 for c in cuts_t]
    sync = sum(1 for dd in near if dd <= 0.08) / max(len(cuts_t), 1)
    chance = min(1.0, len(onsets) * 0.16 / max(dur, 1e-6))
    per_shot = []
    for s in shots:
        m = (t >= s['t_in']) & (t < s['t_out'])
        on = int(((onsets >= s['t_in']) & (onsets < s['t_out'])).sum())
        per_shot.append({'idx': s['idx'], 'rms_db': round(float(rms_db[m].mean()), 1) if m.any() else None,
                         'peak_db': round(float(rms_db[m].max()), 1) if m.any() else None,
                         'onsets': on, 'onsets_per_s': round(on / max(s['dur'], 1e-3), 2),
                         'centroid_hz': int(centroid[m].mean()) if m.any() else None,
                         'hf_ratio_4k': round(float(hf[m].mean()), 3) if m.any() else None})
    step = max(1, int(0.05 * sr / hop))
    out = {'bpm_est': round(bpm, 1), 'onset_count': int(len(onsets)), 'onsets_per_s': round(len(onsets) / dur, 2),
           'onsets': [round(float(o), 3) for o in onsets], 'cut_onset_sync_pct': round(sync * 100, 1),
           'chance_sync_pct': round(chance * 100, 1), 'cut_nearest_onset_s': [round(dd, 3) for dd in near],
           'silence_ratio': round(float(silence.mean()), 3), 'loud_peak_db': round(float(rms_db.max()), 1),
           'loud_median_db': round(float(np.median(rms_db)), 1), 'hf_ratio_4k_mean': round(float(hf.mean()), 3),
           'centroid_hz_median': int(np.median(centroid)), 'ebur128': loudness(src), 'per_shot': per_shot,
           'curve_t': [round(float(q), 3) for q in t[::step]], 'rms_db': [round(float(q), 1) for q in rms_db[::step]],
           'centroid_hz': [int(q) for q in centroid[::step]], 'hf_ratio': [round(float(q), 3) for q in hf[::step]]}
    json.dump(out, open(os.path.join(d, 'audio.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return v['key'], (f"LUFS={out['ebur128'].get('I_LUFS')} onset/s={out['onsets_per_s']} "
                      f"sync={out['cut_onset_sync_pct']}%(chance {out['chance_sync_pct']}%) hf={out['hf_ratio_4k_mean']}")


# ---------- 4. 얼굴(OpenCV Haar, 참고값 — 최종 판단은 눈으로) ----------
def faces(v):
    import cv2
    d = vdir(v); cj = json.load(open(os.path.join(d, 'cuts.json'), encoding='utf-8'))
    fr_c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'))
    pr_c = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, 'haarcascade_profileface.xml'))
    cap = cv2.VideoCapture(os.path.join(d, 'src.mp4')); step = max(1, int(round(cj['fps'] / 5)))
    hits = {}; fi = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if fi % step == 0:
            h0, w0 = fr.shape[:2]; sc = 480 / max(h0, w0)
            g = cv2.cvtColor(cv2.resize(fr, (int(w0 * sc), int(h0 * sc))), cv2.COLOR_BGR2GRAY)
            f1 = fr_c.detectMultiScale(g, 1.15, 6, minSize=(28, 28)); f2 = pr_c.detectMultiScale(g, 1.15, 6, minSize=(28, 28))
            areas = [w * h / (g.shape[0] * g.shape[1]) for (x, y, w, h) in list(f1) + list(f2)]
            hits[fi] = max(areas) if areas else 0.0
        fi += 1
    cap.release()
    per = []
    for s in cj['shots']:
        ks = [k for k in hits if s['f_in'] <= k <= s['f_out']]
        pos = [hits[k] for k in ks if hits[k] > 0]
        per.append({'idx': s['idx'], 'face_frac': round(len(pos) / max(len(ks), 1), 2),
                    'max_face_area_pct': round(max(pos) * 100, 1) if pos else 0.0})
    tot = list(hits.values())
    out = {'note': 'OpenCV Haar 정면+측면 얼굴 검출(0.2초 간격). 손·옆모습·가림은 놓치고 음식 무늬를 얼굴로 착각할 수 있어 참고용',
           'face_time_ratio': round(sum(1 for h in tot if h > 0) / max(len(tot), 1), 3), 'per_shot': per}
    json.dump(out, open(os.path.join(d, 'faces.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return v['key'], f"face_time_ratio={out['face_time_ratio']}"


# ---------- 5. 받아쓰기(faster-whisper medium, 언어 자동) ----------
def whisper_all(vs):
    from faster_whisper import WhisperModel
    # GPU(cuBLAS 12) DLL 이 없어 CPU int8 로 실행 (여러 프로세스로 나눠 돌리기)
    model = WhisperModel('medium', device='cpu', compute_type='int8', cpu_threads=int(os.environ.get('WTHREADS', '6')))
    for v in vs:
        d = vdir(v); out_p = os.path.join(d, 'whisper.json')
        if os.path.exists(out_p):
            continue
        src = os.path.join(d, 'audio_22k.wav')
        if not os.path.exists(src):
            src = os.path.join(d, 'src.mp4')
        segs, info = model.transcribe(src, word_timestamps=True, vad_filter=True, beam_size=5)
        res = [{'start': round(s.start, 2), 'end': round(s.end, 2), 'text': s.text.strip(),
                'no_speech_prob': round(s.no_speech_prob, 2), 'avg_logprob': round(s.avg_logprob, 2),
                'words': [{'s': round(w.start, 2), 'e': round(w.end, 2), 'w': w.word} for w in (s.words or [])]} for s in segs]
        speech = sum(s['end'] - s['start'] for s in res if s['no_speech_prob'] < 0.6)
        json.dump({'language': info.language, 'language_prob': round(info.language_probability, 2),
                   'speech_seconds_est': round(speech, 1),
                   'note': '음악·효과음만 있는 구간은 Whisper가 가짜 문장을 만들 수 있음 → no_speech_prob·화면과 대조',
                   'segments': res}, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print(v['key'], 'whisper', info.language, len(res), 'segs', flush=True)


# ---------- 6. OCR(자막 위치·크기) + 대표색 ----------
def ocr_all(vs):
    import easyocr
    import cv2
    reader = easyocr.Reader(['ko', 'en'], gpu=True, verbose=False)
    for v in vs:
        d = vdir(v); out_p = os.path.join(d, 'ocr_palette.json')
        if os.path.exists(out_p):
            continue
        cj = json.load(open(os.path.join(d, 'cuts.json'), encoding='utf-8')); res = []
        for s in cj['shots']:
            p = os.path.join(d, 'shots', f"s{s['idx']:03d}_m.jpg"); img = cv2.imread(p); h, w = img.shape[:2]; boxes = []
            for (bb, text, conf) in reader.readtext(img):
                if conf < 0.35 or not text.strip():
                    continue
                xs, ys = [q[0] for q in bb], [q[1] for q in bb]
                boxes.append({'x': round(min(xs) / w, 3), 'y': round(min(ys) / h, 3), 'w': round((max(xs) - min(xs)) / w, 3),
                              'h': round((max(ys) - min(ys)) / h, 3), 'text': text, 'conf': round(float(conf), 2)})
            Z = cv2.resize(img, (90, 160)).reshape(-1, 3).astype(np.float32)
            _, lab, cen = cv2.kmeans(Z, 5, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 3,
                                     cv2.KMEANS_PP_CENTERS)
            cnt = np.bincount(lab.flatten(), minlength=5); order = np.argsort(-cnt)
            pal = [{'hex': '#%02x%02x%02x' % tuple(int(c) for c in cen[i][::-1]), 'pct': round(float(cnt[i] / cnt.sum() * 100), 1)}
                   for i in order]
            res.append({'idx': s['idx'], 'text_boxes': boxes, 'palette': pal})
        json.dump({'note': '샷 중간 프레임(360px 폭) OCR. h는 화면 높이 대비 글자 높이 비율', 'shots': res},
                  open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print(v['key'], 'ocr', sum(len(r['text_boxes']) for r in res), 'boxes', flush=True)


# ---------- 7. 댓글(인기순 상위 60, 작성자 이름 저장 안 함) ----------
def comments(v):
    d = vdir(v); out_p = os.path.join(d, 'comments.json')
    if os.path.exists(out_p):
        return v['key'], 'skip'
    r = run(['yt-dlp', '-q', '--no-warnings', '--skip-download', '--write-comments', '--extractor-args',
             'youtube:comment_sort=top;max_comments=60,all,0,0', '-o', os.path.join(d, 'cm'),
             f"https://www.youtube.com/watch?v={v['id']}"], timeout=300)
    p = os.path.join(d, 'cm.info.json')
    if not os.path.exists(p):
        return v['key'], 'FAIL ' + r.stderr[-200:]
    info = json.load(open(p, encoding='utf-8')); cm = info.get('comments') or []
    keep = [{'text': c.get('text', ''), 'likes': c.get('like_count') or 0, 'is_uploader': bool(c.get('author_is_uploader')),
             'pinned': bool(c.get('is_pinned')), 'reply': c.get('parent', 'root') != 'root'} for c in cm]
    json.dump({'note': '작성자 이름은 저장하지 않음', 'description': info.get('description', ''),
               'chapters': info.get('chapters'), 'comments': keep},
              open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    os.remove(p)
    return v['key'], f"{len(keep)} comments"


if __name__ == '__main__':
    step = sys.argv[1]; keys = sys.argv[2:]
    vs = [v for v in VIDS if not keys or v['key'] in keys]
    if step == 'download':
        with ThreadPoolExecutor(6) as ex:
            for k, m in ex.map(download, vs):
                print(k, m, flush=True)
    elif step in ('cuts', 'audio', 'faces', 'timeline'):
        fn = {'cuts': cuts, 'audio': audio, 'faces': faces, 'timeline': timeline}[step]
        with ProcessPoolExecutor(8) as ex:
            for k, m in ex.map(fn, vs):
                print(k, step, m, flush=True)
    elif step == 'whisper':
        whisper_all(vs)
    elif step == 'ocr':
        ocr_all(vs)
    elif step == 'comments':
        with ThreadPoolExecutor(3) as ex:
            for k, m in ex.map(comments, vs):
                print(k, m, flush=True)
