"""질문 세트 전체를 에이전트로 돌려 채점하고 보고서를 쓴다.

실행: python src/eval.py --provider gemini --model gemini-3.5-flash-lite --label run1
- 보고서(공개): outputs/eval_report_<label>.md
- 실행 기록(비공개, 답·도구 호출·토큰): outputs/raw/<label>_runs.jsonl
API 키는 .env(GEMINI_API_KEY·OPENAI_API_KEY)에서 읽고 어디에도 기록하지 않는다.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import agent
from grade import grade, ungrounded_numbers

ROOT = Path(__file__).resolve().parent.parent

# 100만 토큰당 USD(입력, 출력), 유료 등급 표준 가격. 공식 가격 페이지로 확인한 값만 넣는다(2026-10-15 확인)
# - Gemini: ai.google.dev/gemini-api/docs/pricing (2026-12-31까지 가격, 출력에 thinking 포함). 무료 등급으로 실행하면 실제 비용은 0
# - OpenAI: developers.openai.com/api/docs/pricing (캐시 입력 할인은 빼서 조금 높게 잡는다)
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out = PRICES[model]
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def load_set(ids: list[str] | None = None, splits: tuple[str, ...] = ("dev",)) -> list[dict]:
    questions = list(csv.DictReader(open(ROOT / "eval" / "questions.csv", encoding="utf-8")))
    answers = json.loads((ROOT / "eval" / "answers.json").read_text(encoding="utf-8"))
    for q in questions:
        q["checks"] = answers[q["id"]]
    if ids:
        return [q for q in questions if q["id"] in ids]
    return [q for q in questions if q["split"] in splits]


def summarize_result(result: dict) -> dict:
    """기록용으로 도구 결과를 줄인다(행은 앞 5개만)."""
    if "rows" in result:
        return {**result, "rows": result["rows"][:5]}
    if "candidates" in result:
        return {**result, "candidates": result["candidates"][:5]}
    return result


def grounding_sources(q: dict, tool_calls: list) -> list:
    """근거 검사에 쓰는 글: 도구 인자·결과, 질문, 이어지는 대화의 앞 질문·답."""
    calls = [{"arguments": c["arguments"], "result": c["result"]} if isinstance(c, dict)
             else {"arguments": c.arguments, "result": c.result} for c in tool_calls]
    return [calls, q["question"], q.get("prev_question", ""), q.get("prev_answer", "")]


def run_eval(client, model: str, questions: list[dict], log_path: Path | None = None,
             self_check: bool = True) -> list[dict]:
    """문항마다 실행·채점한다. log_path가 있으면 한 문항씩 바로 기록해 중간에 멈춰도 결과가 남는다.
    자기검증이 끼어든 문항은 검증 전 첫 답도 따로 채점해, 검사기가 걸러서 생긴 개선과 모델 자체의 정직함을 구분한다."""
    records = []
    log = open(log_path, "w", encoding="utf-8") if log_path else None
    for q in questions:
        history = None
        if q.get("prev_question"):  # 이어지는 대화: 앞 질문과 고정해 둔 앞 답을 대화 기록으로 넘긴다
            history = [{"role": "user", "content": q["prev_question"]},
                       {"role": "assistant", "content": q["prev_answer"]}]
        try:
            r = agent.run(q["question"], client, model, history=history, self_check=self_check)
        except agent.DailyQuotaExceeded as e:
            print(f"{q['id']}에서 멈춤(한도): {e}")
            break
        tools_called = [c.name for c in r.tool_calls]
        g = grade(r.answer, q["checks"], tools_called, q["expected_tool"])
        # 근거 검사는 기록용으로 줄이기 전의 전체 도구 결과로 한다
        ungrounded = ungrounded_numbers(r.answer, grounding_sources(q, r.tool_calls))
        intervened = bool(r.first_ungrounded)
        first_correct = (grade(r.first_answer, q["checks"], tools_called, q["expected_tool"])["correct"]
                         if intervened else g["correct"])
        records.append({
            "id": q["id"], "split": q["split"], "type": q["type"], "question": q["question"], "answer": r.answer,
            "correct": g["correct"], "tool_ok": g["tool_ok"], "failed_checks": g["failed_checks"],
            "ungrounded": ungrounded,
            "self_check": self_check, "intervened": intervened, "first_answer": r.first_answer,
            "first_ungrounded": r.first_ungrounded if intervened else ungrounded, "first_correct": first_correct,
            "tool_calls": [{"name": c.name, "arguments": c.arguments, "result": summarize_result(c.result)}
                           for c in r.tool_calls],
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "thinking_tokens": r.thinking_tokens,
            "rounds": r.rounds, "seconds": r.seconds, "stopped": r.stopped,
        })
        if log:
            log.write(json.dumps(records[-1], ensure_ascii=False) + "\n")
            log.flush()
        mark = "-" if g["correct"] is None else "O" if g["correct"] else "X"
        print(f"{q['id']} {mark} 도구:{','.join(tools_called) or '-'} 토큰:{r.input_tokens}+{r.output_tokens}"
              + (f" 검증개입:{','.join(r.first_ungrounded)}" if intervened else "")
              + (f" 근거없는수치:{','.join(ungrounded)}" if ungrounded else ""), flush=True)
    if log:
        log.close()
    return records


def regrade(label: str) -> list[dict]:
    """저장된 실행 기록의 답을 현재 채점 규칙으로 다시 채점한다(API 호출 없음).
    근거 검사 기록이 없는 옛 실행은 저장된 도구 결과(앞 5행)로 계산하므로 근거 없음이 실제보다 많게 나올 수 있다."""
    by_id = {q["id"]: q for q in load_set(splits=("dev", "holdout", "holdout_extra", "holdout_ai", "holdout_ai2"))}
    path = ROOT / "outputs" / "raw" / f"{label}_runs.jsonl"
    records = [json.loads(line) for line in open(path, encoding="utf-8")]
    for r in records:
        q = by_id[r["id"]]
        g = grade(r["answer"], q["checks"], [c["name"] for c in r["tool_calls"]], q["expected_tool"])
        if g["correct"] != r["correct"]:
            print(f"{r['id']}: {r['correct']} → {g['correct']}")
        r.update(correct=g["correct"], tool_ok=g["tool_ok"], failed_checks=g["failed_checks"])
        if r.get("intervened"):
            r["first_correct"] = grade(r["first_answer"], q["checks"], [c["name"] for c in r["tool_calls"]],
                                       q["expected_tool"])["correct"]
        if "ungrounded" not in r:
            r["ungrounded"] = ungrounded_numbers(r["answer"], grounding_sources(q, r["tool_calls"]))
    return records


def write_report(records: list[dict], model: str, label: str, provider: str = "", note: str = "") -> Path:
    n = len(records)
    graded = [r for r in records if r["correct"] is not None]  # 기준 애매 문항(정답 없음)은 정답률에서 뺀다
    n_graded = len(graded)
    n_ok = sum(r["correct"] for r in graded)
    n_tool = sum(r["tool_ok"] for r in records)
    tin = sum(r["input_tokens"] for r in records)
    tout = sum(r["output_tokens"] for r in records)
    tthink = sum(r["thinking_tokens"] for r in records)
    cost = cost_usd(model, tin, tout)
    n_ungrounded = sum(bool(r.get("ungrounded")) for r in records)
    checked = any(r.get("self_check") for r in records)
    n_first_ungrounded = sum(bool(r.get("first_ungrounded", r.get("ungrounded"))) for r in records)
    n_first_ok = sum(r.get("first_correct", r["correct"]) for r in graded)
    n_intervened = sum(bool(r.get("intervened")) for r in records)
    by_type = defaultdict(list)
    for r in records:
        by_type[r["type"]].append(r)

    lines = [
        f"# 평가 보고서: {label}",
        "",
        f"- {note or '실행'}: {datetime.now():%Y-%m-%d %H:%M}, 모델 `{model}`" + (f" ({provider})" if provider else ""),
        (f"- 정답률 **{n_ok}/{n_graded} ({n_ok / n_graded:.0%})**" if n_graded else "- 정답률: 채점 문항 없음")
        + (f" (기준 애매·겹침 {n - n_graded}문항은 정답률에서 뺌)" if n_graded < n else "") + f", 도구 선택 {n_tool}/{n}",
        f"- 근거 없는 수치가 나온 답 **{n_ungrounded}/{n}** (답의 숫자가 도구 결과·질문에 없음, 할루시네이션 후보)",
        *([f"- 자기검증 켬: 개입 **{n_intervened}회**. 검증 전 첫 답 기준 근거 없는 수치 {n_first_ungrounded}/{n}, "
           f"정답 {n_first_ok}/{n_graded} (위 수치는 검증 후 최종 답 기준)"] if checked else ["- 자기검증 끔"]),
        f"- 토큰: 입력 {tin:,} · 출력 {tout:,}(생각 {tthink:,} 포함), 문항당 평균 {(tin + tout) / n:,.0f}"
        + (f", 유료 등급 환산 비용 ${cost:.4f}" if cost is not None else ", 비용: 가격 미등록")
        + (" (무료 등급 실행, 실제 비용 0)" if provider == "gemini" else ""),
        "",
        "## 유형별",
        "",
        "| 유형 | 정답 | 도구 선택 |",
        "|---|---|---|",
    ]
    for t, rs in by_type.items():
        g = [r for r in rs if r["correct"] is not None]
        ok = f"{sum(r['correct'] for r in g)}/{len(g)}" if g else "채점 안 함"
        lines.append(f"| {t} | {ok} | {sum(r['tool_ok'] for r in rs)}/{len(rs)} |")
    lines += ["", "## 문항별", "",
              "| ID | 유형 | 정답 | 도구 | 근거 없는 수치 | 검증 개입(첫 답의 수치) | 호출한 도구 | 답(앞 80자) |",
              "|---|---|---|---|---|---|---|---|"]
    for r in records:
        called = ", ".join(c["name"] for c in r["tool_calls"]) or "-"
        ans = r["answer"].replace("\n", " ").replace("|", "\\|")[:80]
        mark = "-" if r["correct"] is None else "O" if r["correct"] else "X"
        lines.append(f"| {r['id']} | {r['type']} | {mark} | "
                     f"{'O' if r['tool_ok'] else 'X'} | {', '.join(r.get('ungrounded', [])) or '-'} | "
                     f"{', '.join(r['first_ungrounded']) if r.get('intervened') else '-'} | {called} | {ans} |")

    out = ROOT / "outputs" / f"eval_report_{label}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_repeat_report(labels: list[str], label: str) -> Path:
    """같은 세트를 여러 번 돌린 실행 기록을 비교한다: 실행별 정답률, 매번 맞지는 않은 문항(답의 흔들림)."""
    runs = {lb: {r["id"]: r for r in map(json.loads, open(ROOT / "outputs" / "raw" / f"{lb}_runs.jsonl",
                                                       encoding="utf-8"))} for lb in labels}
    ids = list(runs[labels[0]])
    assert all(list(rs) == ids for rs in runs.values()), "실행마다 문항이 다르다"
    k = len(labels)
    lines = [f"# 반복 실행 비교: {label}", "", f"- 실행 {k}번: {', '.join(labels)} (문항 {len(ids)}개씩)", "",
             "| 실행 | 정답 | 근거 없는 수치가 나온 답 | 자기검증 개입 | 모델 호출 |", "|---|---|---|---|---|"]
    for lb, rs in runs.items():
        rows = rs.values()
        g = [r for r in rows if r["correct"] is not None]
        lines.append(f"| {lb} | {sum(r['correct'] for r in g)}/{len(g)} | "
                     f"{sum(bool(r.get('ungrounded')) for r in rows)} | "
                     f"{sum(bool(r.get('intervened')) for r in rows) if any(r.get('self_check') for r in rows) else '꺼짐'}"
                     f" | {sum(r['rounds'] for r in rows)} |")
    graded_ids = [i for i in ids if runs[labels[0]][i]["correct"] is not None]
    always = sum(all(runs[lb][i]["correct"] for lb in labels) for i in graded_ids)
    lines += ["", f"- **{k}번 모두 정답: {always}/{len(graded_ids)}**", "", "## 매번 맞지는 않은 문항", "",
              "| ID | 유형 | 맞은 횟수 | 근거 없는 수치(검증 전 첫 답 포함) | 질문 |", "|---|---|---|---|---|"]
    for i in ids:
        rs = [runs[lb][i] for lb in labels]
        n_ok = sum(bool(r["correct"]) for r in rs)
        ung = sorted({x for r in rs for x in r.get("ungrounded", []) + r.get("first_ungrounded", [])})
        if (rs[0]["correct"] is not None and n_ok < k) or ung:
            lines.append(f"| {i} | {rs[0]['type']} | {n_ok}/{k} | {', '.join(ung) or '-'} | {rs[0]['question']} |")
    out = ROOT / "outputs" / f"eval_report_{label}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=list(agent.PROVIDERS), default="gemini")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--label", required=True, help="결과 파일 이름에 붙일 이름, 예: run1")
    ap.add_argument("--ids", nargs="*", help="일부 문항만, 예: Q01 Q22")
    ap.add_argument("--splits", nargs="*", default=["dev"],
                    help="dev(개선용) / holdout / holdout_extra / holdout_ai·holdout_ai2(외부 AI 질문). 홀드아웃은 개선이 끝난 뒤에만 돌린다")
    ap.add_argument("--no-check", action="store_true",
                    help="자기검증을 끄고 실행한다(켰을 때와 비교용)")
    ap.add_argument("--regrade", metavar="LABEL",
                    help="API를 부르지 않고 저장된 실행 기록을 다시 채점해 --label 이름으로 보고서를 쓴다")
    ap.add_argument("--compare", nargs="+", metavar="LABEL",
                    help="API를 부르지 않고 여러 실행 기록을 비교해 --label 이름으로 보고서를 쓴다")
    args = ap.parse_args()

    if args.compare:
        print(f"보고서: {write_repeat_report(args.compare, args.label).relative_to(ROOT)}")
        return

    if args.regrade:
        records = regrade(args.regrade)
        note = f"{args.regrade} 실행 기록을 다시 채점(API 호출 없음)"
        print(f"보고서: {write_report(records, args.model, args.label, args.provider, note).relative_to(ROOT)}")
        return

    load_dotenv(ROOT / ".env")
    client = agent.make_client(args.provider)
    raw = ROOT / "outputs" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    questions = load_set(args.ids, tuple(args.splits))
    records = run_eval(client, args.model, questions, raw / f"{args.label}_runs.jsonl", not args.no_check)
    if not records:
        return
    if len(records) < len(questions):
        print(f"주의: {len(questions)}문항 중 {len(records)}문항만 실행됨")
    print(f"보고서: {write_report(records, args.model, args.label, args.provider).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
