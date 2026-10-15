# 서울 지하철 접근성 GIS 질의 에이전트

> 작업 중(2026-10-14 시작). 평가 결과가 나오면 첫 표에 정답률을 적습니다.

서울 법정동별 지하철 접근성 데이터에 자연어로 질문하면, LLM이 읽기 전용 도구(SQL·동 찾기)를 골라 실행하고 그 결과로만 답하는 작은 에이전트입니다. 질문 세트의 정답을 코드로 따로 계산해 에이전트 답을 자동 채점합니다.

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
python src/eval.py --model gemini-3.5-flash-lite --label run1   # 개선용 48문항 평가
python src/eval.py --model gemini-3.5-flash-lite --label run1_regrade --regrade run1   # 저장된 답 다시 채점(API 호출 없음)
```

## 폴더 구조

```text
data/       에이전트가 조회하는 데이터(공개 CSV 사본)
src/
  tools.py    읽기 전용 도구: run_sql(SELECT만, 거리 함수 dist_m), find_dong(동 이름 → 법정동)
  agent.py    function calling 루프(OpenAI 호환 Chat Completions, 기본 Gemini, 프레임워크 없음)
  answers.py  평가 정답 계산(pandas, 에이전트와 다른 경로) → eval/answers.json
  grade.py    규칙 기반 채점(LLM 없음), 근거 없는 수치 검사
  eval.py     질문 세트 전체 실행·채점 → outputs/eval_report_<이름>.md
  app.py      Streamlit 화면: 질문·답·에이전트가 한 일(SQL·결과)·근거 없는 수치·토큰
eval/       평가 질문 120개(개선용 48 + 홀드아웃 72, questions.csv)와 정답 규칙(answers.json)
tests/      도구·정답·채점기·에이전트 루프·화면 테스트(API 호출 없음)
outputs/    평가 보고서(원본 실행 기록 outputs/raw/는 비공개)
docs/       진행 과정·의사결정·작업일지·AI 활용 기록
```

## 진행 과정

단계별 설명은 [`docs/진행_과정.md`](docs/진행_과정.md), 선택의 근거는 [`docs/의사결정/`](docs/의사결정/)에 있습니다.
