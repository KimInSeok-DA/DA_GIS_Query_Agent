"""에이전트 답을 정답 규칙(eval/answers.json)으로 채점한다. LLM을 쓰지 않는 규칙 기반 채점이다."""

import re

# 1,234.5 / 1234 / 0.63 같은 숫자와, 바로 뒤의 단위(km·m·%·㎢ 등)
_NUM_RE = re.compile(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(㎢|km²|km2|km|㎞|m|%)?")
# 거절: 한 문장 안에 '데이터/정보/자료/목록'과 부정 표현이 함께 있으면 인정한다(1015_09·1015_10).
# "버스 정류장 개수 데이터는 없습니다", "제공된 데이터에는 … 보행 시간 정보는 없습니다" 등
_REFUSE_RE = re.compile(
    r"[^.!?\n]*(데이터|정보|자료|목록)[^.!?\n]*"
    r"(없|포함되어\s*있지\s*않|들어\s*있지\s*않|제공되지\s*않|존재하지\s*않|확인되지\s*않)"
)
# 되묻기: 물음표로 끝나는 문장이 있거나 "어느/어떤 구"를 묻는다
_CLARIFY_RE = re.compile(r"\?|어느\s*구|어떤\s*구|어느\s*쪽|어떤\s*쪽")


def _nospace(s: str) -> str:
    """띄어쓰기는 사용자마다 달라서 글자 비교에서는 무시한다."""
    return re.sub(r"\s+", "", s)


def numbers_in(answer: str, unit: str = "") -> list[float]:
    """답에 나온 숫자들. 기대 단위가 m이면 km로 쓴 숫자는 ×1000 해서 m로 맞춘다."""
    found = []
    for raw, u in _NUM_RE.findall(answer):
        v = float(raw.replace(",", ""))
        if unit == "m" and u in ("km", "㎞"):
            v *= 1000
        found.append(v)
    return found


def check_one(answer: str, check: dict) -> bool:
    kind = check["kind"]
    if kind == "text":
        return _nospace(check["value"]) in _nospace(answer)
    if kind == "number":
        return any(abs(v - check["value"]) <= check["tol"] + 1e-9 for v in numbers_in(answer, check.get("unit", "")))
    if kind == "refuse":
        return bool(_REFUSE_RE.search(answer))
    if kind == "clarify":
        return bool(_CLARIFY_RE.search(answer))
    if kind == "present":
        # 이 표현이 있어야 한다. 띄어쓰기를 지운 답에 대해 찾는다(예: 동점을 알렸는가)
        return bool(re.search(check["pattern"], _nospace(answer)))
    if kind == "one_of":
        # 여러 답 방식 중 하나만 맞으면 된다. options는 check 목록의 목록(목록 안은 모두 통과해야 함)
        return any(all(check_one(answer, c) for c in opt) for opt in check["options"])
    if kind == "absent":
        # 지어낸 표현이 없어야 한다(예: 도보 시간 질문에 "15분")
        return not re.search(check["pattern"], answer)
    raise ValueError(f"모르는 check 종류: {kind}")


# 근거 검사에서 빼는 숫자: 목록 번호("1. ", "2) ")와 순위("2위")
_LIST_MARK_RE = re.compile(r"(?m)^[\s*>-]*\**\d+[.)]\s|\d+\s*위")


def _numbers_in_sources(obj, out: list[float]) -> list[float]:
    """도구 인자·결과(중첩 dict·list)와 질문 글에 나온 숫자를 모두 모은다. 문자열 안 숫자(명동2가, cover_500m)도 포함."""
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers_in_sources(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in_sources(v, out)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(numbers_in(obj))
    return out


def ungrounded_numbers(answer: str, sources) -> list[str]:
    """답에 나온 숫자 중 도구 결과·질문 어디에도 없는 것(할루시네이션 후보, 1015_10).

    답에 쓴 자릿수로 반올림해 같으면 근거가 있는 것으로 본다(630.357143 → 630.36·630).
    m↔km 환산도 같은 값으로 본다. 모델이 도구 없이 직접 계산한 값(290−256=34 등)도 여기에 걸린다.
    """
    src = _numbers_in_sources(sources, [])
    text = _LIST_MARK_RE.sub(" ", answer)
    found = []
    for raw, _unit in _NUM_RE.findall(text):
        v = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -decimals + 1e-9
        if not any(abs(v - x) <= tol or abs(v - x / 1000) <= tol or abs(v - x * 1000) <= tol for x in src):
            found.append(raw)
    return found


def grade(answer: str, checks: list[dict], tools_called: list[str], expected_tool: str) -> dict:
    """checks를 모두 통과하면 정답. 도구 선택은 따로 센다(expected_tool이 none이면 항상 맞음).
    checks가 비어 있으면(정답을 하나로 정할 수 없는 문항) correct는 None — 정답률에서 뺀다."""
    failed = [c for c in checks if not check_one(answer, c)]
    tool_ok = expected_tool == "none" or expected_tool in tools_called
    return {"correct": not failed if checks else None, "tool_ok": tool_ok, "failed_checks": failed}
