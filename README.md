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
cp .env.example .env   # OPENAI_API_KEY 입력
```

## 진행 과정

단계별 설명은 [`docs/진행_과정.md`](docs/진행_과정.md), 선택의 근거는 [`docs/의사결정/`](docs/의사결정/)에 있습니다.
