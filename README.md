# 서울 지하철 접근성 GIS 질의 에이전트

서울 법정동별 지하철 접근성 데이터에 자연어로 질문하면, LLM이 읽기 전용 도구(SQL·동 찾기)를 골라 실행하고 그 결과로만 답하는 작은 에이전트입니다. 질문 세트의 정답을 코드로 따로 계산해 에이전트 답을 자동 채점합니다.

## 평가 결과

모델 `gemini-3.5-flash-lite`(무료 등급), 자기검증 켬. 정답은 코드로 계산했고, 홀드아웃 정답 규칙은 실행 전에 커밋했습니다.

| 질문 세트 | 문항 | 정답 (자동 채점) | 근거 없는 수치가 나온 답 (검증 전 첫 답 → 최종) | 모델 호출 | 유료 환산 비용 |
|---|---|---|---|---|---|
| 개선용 (프롬프트를 고치며 본 질문) | 48 | 48/48 | 2/48 → 0/48 | 107 | $0.045 |
| 홀드아웃 (직접 만들고 개선 때 보지 않은 질문) | 72 | **71/72** | 0/72 → 0/72 | 152 | $0.065 |
| 외부 AI 질문 (데이터 구조를 모르는 다른 AI가 쓴 질문) | 30 | **16/20** (기준 애매 10문항 제외) | 4/30 → 0/30 | 82 | $0.054 |

- 실제 비용은 0입니다(무료 등급). 각 세트 1번 실행한 결과입니다
- **정답률과 근거 없는 수치는 따로 셉니다.** 근거 없는 수치는 답의 숫자가 도구 결과·질문에 없는 경우(할루시네이션 후보)입니다
- **자기검증**: 답에 근거 없는 수치가 있으면 그 숫자를 알려 주고 1번 다시 답하게 합니다. 검사기가 걸러서 생긴 0을 모델의 정직함으로 보지 않도록, 검증 전 첫 답 기준도 함께 적습니다
- 사람이 답을 읽어 검토하면 외부 AI 질문은 17/20입니다(A27은 맞는 답인데 채점 규칙이 놓침). 점수는 고치지 않고 따로 적습니다
- 같은 출제자의 홀드아웃(99%)보다 **다른 출제자의 질문(80%)에서 오류가 더 나왔습니다.** 여러 값이 든 열(`운영기관`)을 나누지 않고 센 답, "걸어서 5분"을 400m로 가정해 환산한 답, SQL에서 하나를 두 번 뺀 답 등입니다. 분석: [1016_02](docs/의사결정/1016_02_홀드아웃_결과와_분석.md)

## 한계

- 질문 수가 적습니다. 외부 AI 질문은 자동 채점 20문항이라 1문항이 5%p입니다
- 외부 질문도 AI(ChatGPT 무료)가 썼습니다. 사람이 직접 쓴 질문보다 정돈되어 있을 수 있습니다
- 근거 검사는 숫자만 봅니다. 지어낸 역·동 이름은 잡지 못하고, 모델이 SQL에 직접 넣은 숫자(가정한 기준값 등)는 근거로 인정되어 통과합니다
- 규칙 채점은 "하지 말아야 할 것"은 잘 잡지만 "했어야 할 것"을 놓칠 수 있습니다. 그래서 오답·기준 애매 답·일부 정답을 사람이 읽었습니다
- 거리는 동 대표점에서 역까지의 직선거리입니다. 실제 걷는 거리·시간이 아닙니다
- 역 이름이 같은 역(신촌 2개)이 있어 역 이름으로 표를 결합하면 틀릴 수 있습니다
- Gemini 무료 등급은 입력이 제품 개선에 쓰일 수 있습니다. 보내는 내용은 질문과 공개 데이터 조회 결과뿐입니다

## 데이터

[DA_Seoul_Subway_Access_GIS](https://github.com/KimInSeok-DA/DA_Seoul_Subway_Access_GIS)의 공개 결과 파일(법정동 467개, 역 389개)을 씁니다. 원 출처와 이용 조건은 그 저장소 README의 "데이터 출처"를 따릅니다.

| 파일 | 원본 | 내용 |
|---|---|---|
| `data/emd.csv` | `docs/downloads/seoul_subway_access_emd.csv` | 법정동별 가장 가까운 역·거리(대표점 기준 직선거리), 동 안 역 수, 역 500m 반경 면적 비율 |
| `data/stations.csv` | `docs/downloads/seoul_subway_access_stations.csv` | 역 이름·노선·운영기관·좌표 |

원 출처: 공공데이터포털(국가철도공단 전국도시철도역사정보표준데이터, 국토교통부 법정동코드·행정구역도), 서울 열린데이터광장(서울시 역사마스터 정보). 공공누리 제1유형(출처표시) 또는 이용허락범위 제한 없음.

## 실행

```bash
uv venv -p 3.14 .venv
uv pip install -r requirements.txt
cp .env.example .env   # GEMINI_API_KEY 입력(무료 등급 가능)
source .venv/bin/activate   # Windows cmd: .venv\Scripts\activate, PowerShell: .venv\Scripts\Activate.ps1

streamlit run src/app.py                          # 질문 화면(API 키는 .env 또는 사이드바 입력)
python -m pytest                                  # 테스트(API 호출 없음)
python src/answers.py                             # 정답 다시 계산
python src/eval.py --model gemini-3.5-flash-lite --label run1   # 개선용 48문항 평가(자기검증 켬, --no-check로 끔)
python src/eval.py --model gemini-3.5-flash-lite --label run1_regrade --regrade run1   # 저장된 답 다시 채점(API 호출 없음)
```

## 폴더 구조

```text
data/       에이전트가 조회하는 데이터(공개 CSV 사본)
src/
  tools.py    읽기 전용 도구: run_sql(SELECT만, 거리 함수 dist_m), find_dong(동 이름 → 법정동)
  agent.py    function calling 루프(OpenAI 호환 Chat Completions, 기본 Gemini, 프레임워크 없음), 근거 없는 수치 자기검증
  answers.py  평가 정답 계산(pandas, 에이전트와 다른 경로) → eval/answers.json
  grade.py    규칙 기반 채점(LLM 없음), 근거 없는 수치 검사
  eval.py     질문 세트 전체 실행·채점 → outputs/eval_report_<이름>.md
  app.py      Streamlit 화면: 질문·답·에이전트가 한 일(SQL·결과)·근거 없는 수치·토큰
eval/       평가 질문 150개(개선용 48 + 홀드아웃 72 + 외부 AI 질문 30, questions.csv)와 정답 규칙(answers.json)
tests/      도구·정답·채점기·에이전트 루프·화면 테스트(API 호출 없음)
outputs/    평가 보고서(원본 실행 기록 outputs/raw/는 비공개)
docs/       진행 과정·의사결정·작업일지·AI 활용 기록
```

## 진행 과정

단계별 설명은 [`docs/진행_과정.md`](docs/진행_과정.md), 선택의 근거는 [`docs/의사결정/`](docs/의사결정/)에 있습니다.
