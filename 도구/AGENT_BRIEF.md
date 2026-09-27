# 쇼츠 컷별 분석 JSON 작성 지침 (청담언니 22개 + 개별 영상 8개 공통)

역할: 세계 최고 수준의 숏폼 편집자·감독·사운드 디자이너. 쇼츠 1개를 **컷 단위로 완전 분해**해 `videos/<키>/analysis.json` 1개를 쓴다.
이 분석은 예전 "김햄찌 영상분석"과 같은 깊이(컷별 분해·떡상 공식·소리·편집 키트)로 하되, 사용자가 특히 궁금한 것에 초점을 맞춘다:

1. **소재·어그로(훅)** — 무엇을 소재로 골랐고, 제목·첫 프레임·첫 3초가 어떻게 손가락을 멈추게 하나
2. **앵글** — 탑다운·매크로·하이앵글 등 어떤 각도를 몇 컷씩, 왜
3. **빠른 컷(빡빡빡)** — 컷 길이·연타 구간·배속·리듬이 무엇에 맞춰 잘리나
4. **소리·ASMR** — 바삭·쨍·찰랑 같은 현장음을 어떻게 키우고, 음악·효과음과 어떻게 섞나
5. **편집 퀄·효과** — 전환·줌 펀치·배속·자막 애니메이션 등 다른 채널보다 "확실히 다른" 지점
6. **사람 얼굴 vs 물체** — 얼굴이 나오는 컷, 손만 나오는 컷, 물체만 나오는 컷의 비율과 역할

## 1. 먼저 볼 것 (작업 폴더 = 이 파일의 두 단계 위 `work/`, 모든 경로는 work 기준)
- `data/videos.json` — 내 키(c01~c22 = 청담언니 선정 순위, s1~s8 = 사용자가 준 개별 영상)의 제목·조회수·댓글·섹터
- `videos/<키>/cuts.json` — 컷 번호(idx)·시작·끝·길이·밝기·움직임. **컷 번호와 시간은 이 파일 그대로**(합치거나 나누지 말 것. 검출 오류는 cut_type 으로 표시)
- `videos/<키>/sheets/sheet_XX.jpg` — 콘택트시트(1장 = 4컷, 행 = 컷 1개: 시작|중간|끝). **Read 도구로 전부 본다**
- `videos/<키>/hook_0-3s.jpg` (처음 3초, 0.2초 간격 15장), `ending_last3s.jpg` (마지막 3초), `src.jpg`(유튜브 썸네일, 있으면)
- `videos/<키>/timeline_XX.jpg` — 컷과 무관하게 **1초 간격** 전체 흐름(1장 = 20초). 긴 컷 안의 동작·자막 변화, 놓친 점프컷 확인용. **전부 본다**
- 개별 영상 중 상단 제목 바·하단 로고 같은 **고정 틀(템플릿)** 이 있는 영상은 cuts.json 의 `active_box`(실제로 움직이는 영역)만으로 컷을 검출했다. 틀 자체(제목 바 문구·색·로고)는 훅 장치로 따로 분석할 것
- 검출기가 놓친 컷이 timeline 에서 보이면: 번호는 그대로 두고 해당 컷 `act`/`fx` 에 "컷 안 점프컷 N회(약 12.5s·20.9s)"처럼 적고, pacing.summary 에 "검출 누락 추정 N개 포함 시 실제 분당 컷 ≈ X"를 따로 적는다
- 확대가 필요하면 `videos/<키>/shots/sNNN_a.jpg|_m.jpg|_z.jpg`(360×640, NNN = 컷 번호 3자리)
- `audio.json` — LUFS(ebur128)·온셋(소리 타격점) 수·초당 온셋·컷-온셋 일치율(`cut_onset_sync_pct`) vs 우연 기준(`chance_sync_pct`)·무음 비율·고역비(`hf_ratio_4k`, 4kHz 이상 에너지 비율 = 바삭/쨍 ASMR 지표)·컷별 값(`per_shot`)
- `spectrogram.png` — 소리 지도(가로 = 시간, 세로 = 주파수. 세로 줄무늬 = 타격음)
- `whisper.json` — 말소리 받아쓰기(언어 자동). 음악만 있으면 가짜 문장이 생길 수 있으니 `no_speech_prob`·화면과 대조
- `ocr_palette.json` — 컷별 화면 글자(위치 x,y·높이 h = 화면 대비 비율)·대표색
- `faces.json` — OpenCV 얼굴 검출 참고값(놓침·오검출 있음 → 최종은 눈으로)
- `comments.json` — 인기 댓글 60개 + 설명란(작성자 이름 없음)

## 2. JSON 구조 (키는 영어, 값은 한국어. prompt 만 영어)
최상위 필수 키:
```
key, group("chengdam"|"single"), rank, id, fmt, sector, logline, why[], formula[],
hook{title_hook, first_frame, first_1s, first_3s, text_hook, aggro_types[], promise_payoff, retention_devices[], ending_loop, score, score_note},
topic{material, novelty, trend_hook, series},
visual{people{face_pct, hands_pct, object_only_pct, face_role, note}, angles[{name, shots[], pct, why}], sizes{ECU,CU,MS,WS}, look, signature_shots[]},
pacing{summary, cuts_real, avg_shot_s, median_shot_s, cpm, fastest_run, slowest, speed_ramps, rhythm_note, curve[{t0,t1,cps,note}]},
sound{summary, layers{asmr,bgm,voice,sfx}, asmr[{t,n,type,how}], sfx[{t,n,type,role}], bgm{guess,role,level}, voice{present,type,timing}, mix, sound_first},
edit_fx{summary, transitions[{type,count,shots[]}], effects[{name,shots[],how}], grade, quality_diff[]},
captions{summary, styles[{name,spec,use}], density, note},
beats[{name,t0,t1,e,desc}],
comments_insight{themes[{theme,share,example_paraphrase}], what_triggers_comments, uploader_pin},
shots[], tech[], adapt{keep[], change[], idea_ai_shorts, idea_live_action},
kit{shoot_list[], edit_recipe[], sfx_search[]}
```
- `sector`: 청담언니는 data/videos.json 의 sector 키 그대로(drink, ice, dessert, cook, ng, asmr, mass, ad, life). 개별 영상은 장르를 짧게(예: "전화 사연 AI 애니", "펫 AI 드라마", "뷰티 정보", "생활 꿀팁", "여행 브이로그", "홈바 레시피")
- `hook.score`: 1~10 정수(훅 강도). `beats[].e`: -1~+1(흥분·감정 강도)
- `visual.people.*_pct`, `pacing.*`: 숫자. face/hands/object_only 는 **컷 길이 가중 %**(합이 100 근처일 필요는 없음 — 얼굴+손 동시 가능)
- `pacing.cuts_real` = cut_type 이 "false" 가 아닌 컷 수. `cpm` = 분당 컷(cuts_real ÷ 길이 × 60)
- `pacing.curve`: 5초 단위 초당 컷 수(cps)와 메모 — 빡빡빡 구간이 어디인지 보이게
- `sound.asmr` 8~20개, `sound.sfx` 0~20개(실제 들린/보인 근거가 있는 것만. 추측이면 "추정"). `t` 는 초(소수 1자리), `n` 은 컷 번호
- `edit_fx.quality_diff` 3~5개: "다른 요리/정보 쇼츠 대비 이 영상 편집이 확실히 다른 점"
- `comments_insight.themes` 3~6개, share 는 "약 40%" 같은 대략 비율, example_paraphrase 는 **의역**(원문 복사 금지)
- `tech` 10개 이상(컷 번호 포함), `kit.edit_recipe` 6~10단계(CapCut/프리미어에서 그대로 따라 할 순서), `kit.sfx_search` 영어 검색어 8~15개

### 컷 객체(shots[] 원소) — 전부 필수, cuts.json 컷 수와 같은 개수, n = 1..N 순서
```
{"n":1, "cut_type":"hard", "subj":"object", "sz":"ECU", "ang":"탑다운", "cam":"고정", "speed":"1x",
 "act":"...", "asmr":"...", "sfx":"", "cap":"", "fx":"...", "role":"hook", "why":"...", "shoot":"...", "prompt":"..."}
```
- `cut_type`: hard(일반 컷) | jump(같은 구도에서 시간만 건너뜀) | match(모양·동작 맞춤 컷) | whip(휩/스와이프 전환) | dissolve | flash(0.2초 미만 섬광·전환 프레임) | false(검출 오류 — 앞 컷과 끊김 없이 이어지는 같은 장면. 번호는 유지하고 이렇게 표시)
- `subj`: face(얼굴이 주인공) | face_hands | hands(손+물체, 얼굴 없음) | object(물체만) | person(몸은 보이나 얼굴 안 보임) | text(글자 카드) | mixed
- `sz`: ECU | CU | MCU | MS | WS | EWS | insert
- `ang`(아래 표현 중 골라 쓰기, 필요하면 "탑다운 → 45°" 처럼 변화 표기): 탑다운 | 하이앵글 45° | 아이레벨 | 로우앵글 | 매크로 | 측면 | 정면 | POV | 셀카 | 부감 와이드
- `cam`: 고정 | 푸시인 | 풀아웃 | 팬 | 틸트 | 핸드헬드 | 회전 | 트래킹 | 편집 줌(펀치인) | 크래시 줌 — 조합 가능
- `speed`: 1x | 2x | 3x | 4x+ | 슬로모 | 타임랩스 | 역재생 | 스피드 램프 | 프리즈 (눈으로 판단 + motion_mean 참고)
- `act`: 화면에서 일어나는 일 1~2문장
- `asmr`: 이 컷의 현장음 성격(예: "얼음 깨지는 쨍 소리 강조, 음악 줄임") — 없으면 "음악만" / "무음"
- `sfx`: 편집으로 넣은 효과음(뽁·뾰로롱·휙·띠링·웃음 등) — 없으면 ""
- `cap`: 화면 자막의 **의도 요약**(원문 문장 복사 금지, 1~3단어 조각까지만) — 없으면 ""
- `fx`: 들어올 때 전환 + 컷 안 효과(줌 펀치, 흔들림, 스티커, 이모지, 텍스트 팝, 분할, 색 변화…) — 없으면 "하드컷"
- `role`: hook | setup | build | tension | reveal | payoff | reaction | rehook | cta | loop | broll
- `why`: 이 컷이 여기 있는 이유(시청 유지·기대·보상 관점) 1문장
- `shoot`: 재현 촬영·편집 팁 1문장(한국어, 렌즈 거리·조명·소품·마이크 위치 등 구체적으로)
- `prompt`: AI 영상 재현용 **영어** 1~2문장(shot size, angle, subject, action, lighting, sound cue). 실존 인물·브랜드 이름 금지("a cheerful woman in her 40s", "a jelly ice bar" 처럼 일반화)

## 3. 품질 기준
- `why` 5~6개: 구체적 숫자(조회수·컷 수·초·일치율)와 컷 번호 포함. 막연한 말("임팩트 있다") 금지
- `formula` 8~12단계, 영상 흐름 순서
- 훅 분석은 hook_0-3s.jpg 를 0.2초 단위로 읽고 "0.0s …, 0.4s …" 처럼 시각을 적어라. 첫 프레임이 썸네일 역할을 하는지 판단
- 소리 분석은 audio.json 수치를 인용(LUFS, 초당 온셋, 컷-온셋 일치율 vs 우연 기준, 고역비). 일치율이 우연보다 확실히 높으면 "소리(타격음)에 맞춘 편집", 비슷하면 "동작·자막 타이밍 편집"으로 해석
- 얼굴 비율은 faces.json 참고값과 눈으로 본 값이 다르면 note 에 둘 다 적기
- 모르는 것은 "추정" 또는 "확인 불가"라고 쓰기. 지어내지 말 것
- 개별 영상(s1~s8)은 채널 전체가 아니라 **이 영상 하나만** 분석(채널 정보는 구독자 수 정도만 참고)

## 4. 저작권 (엄격 — 결과는 공개 저장소에 올라감)
- 원본 자막·대사·댓글 문장을 **옮겨 적지 말고 의도만 요약**. 따옴표 인용은 1~3단어 조각까지만
- 댓글은 의역. 작성자 이름·아이디 금지
- 제목은 data/videos.json 에 이미 있으니 분석 본문에 통째로 반복하지 말 것

## 5. 검증 (반드시 실행, 통과할 때까지 고치기)
`PYTHONUTF8=1 python tools/validate.py <키>` — 컷 수·필수 키·허용 값·숫자 범위·원문 복사(12자 이상 연속 일치) 검사. 출력이 `OK` 로 끝나야 완료.
다른 영상 폴더·다른 파일은 수정 금지. 최종 답변(반환값)은 아래 요약 JSON 만.
