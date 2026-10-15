# HANDOFF

## 현재 상태 (2026-10-15)

- 준비 끝: 설정 파일, 데이터 사본(원본과 해시 일치), `.venv`(Python 3.14.5)·`requirements.txt`, 문서 틀(`docs/진행_과정.md`·의사결정 1015_01～03)
- 원격: `origin` = github.com/KimInSeok-DA/DA_GIS_Query_Agent, `main`에 README 첫 커밋
- 작업 흐름: 작업 단위 브랜치 → 커밋·푸시 → PR, 사용자 판단 지점에서 멈춤(1015_03)
- 폴더: `src/`(도구·에이전트·정답 계산), `eval/`(평가 질문 세트), `tests/`(도구 단위 테스트), `outputs/`(평가 보고서)

## 다음 작업

1. `feat/tools`: `run_sql`·`find_dong` + pytest
2. `feat/eval-set`: 질문 세트·pandas 정답·채점기 → 사용자 검토
3. `feat/agent-loop`: function calling 루프 → 모델 선택·1차 채점 비용 승인 받기

## 열린 결정

- 사용할 모델(공식 문서로 가격·function calling 확인 후 사용자 결정)
- 저장소 공개 시점(사용자)
