"""README·포트폴리오용 그림을 docs/images/에 만든다.

수치는 README "평가 결과" 표와 같다(각 값의 출처: outputs/eval_report_*.md).
실행: python scripts/make_charts.py  (matplotlib 필요, 에이전트·API와 무관)
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"

plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 기본 한글 글꼴
plt.rcParams["axes.unicode_minus"] = False

SURFACE = "#ffffff"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e1"
BLUE = "#2a78d6"     # 직접 만든 질문 / 강조
ORANGE = "#eb6834"   # 외부 AI 질문
BLUE_LIGHT = "#86b6ef"
BLUE_DARK = "#1c5cab"

# (이름, 설명, 맞힌 수, 채점 문항 수, 출제자)
ACCURACY = [
    ("개선용", "프롬프트를 고치며 본 질문", 48, 48, "self"),
    ("홀드아웃", "직접 만들고 개선 때 보지 않은 질문", 71, 72, "self"),
    ("외부 AI 1차", "데이터 구조를 모르는 다른 AI가 쓴 질문", 16, 20, "ext"),
    ("외부 AI 2차", "1차 오류를 고친 뒤 새 질문", 21, 21, "ext"),
    ("외부 AI 3차", "2차 오류를 고친 뒤 새 질문", 21, 25, "ext"),
]

# (이름, 전체 문항, 검증 전 첫 답, 최종 답, 메모)
GROUNDING = [
    ("개선용", 48, 2, 0, ""),
    ("홀드아웃", 72, 0, 0, ""),
    ("외부 AI 1차", 30, 4, 0, ""),
    ("외부 AI 2차", 50, 5, 2, "최종 2개는 검사기 오탐"),
    ("외부 AI 3차", 50, 11, 0, ""),
]


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_accuracy():
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    rows = ACCURACY[::-1]
    y = range(len(rows))
    pct = [c / n * 100 for _, _, c, n, _ in rows]
    colors = [BLUE if who == "self" else ORANGE for *_, who in rows]
    ax.barh(y, pct, height=0.56, color=colors, edgecolor=SURFACE, linewidth=2)
    for i, (name, desc, c, n, _) in enumerate(rows):
        ax.text(pct[i] + 1.2, i, f"{c}/{n}  ({c / n:.0%})", va="center", color=INK, fontsize=11)
    ax.set_yticks(list(y), [f"{name}\n{desc}" for name, desc, *_ in rows], fontsize=9.5, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_title("질문 세트별 정답률 (코드로 계산한 정답과 자동 대조)", loc="left", fontsize=13, color=INK, pad=26)
    ax.text(0, 1.03, "외부 AI 질문은 정답을 하나로 정할 수 없는 질문을 빼고 채점  ·  모델 gemini-3.5-flash-lite",
            transform=ax.transAxes, fontsize=9, color=INK2)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
              labels=["직접 만든 질문", "다른 AI가 쓴 질문"], loc="upper center", bbox_to_anchor=(0.45, -0.09), ncol=2, frameon=False, fontsize=9.5,
              labelcolor=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "chart_accuracy.png", dpi=200)
    plt.close(fig)


def chart_grounding():
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    _style(ax)
    rows = GROUNDING[::-1]
    h = 0.34
    for i, (name, total, first, final, note) in enumerate(rows):
        for off, val, color in ((h / 2, first, BLUE_LIGHT), (-h / 2, final, BLUE_DARK)):
            p = val / total * 100
            ax.barh(i + off, p, height=h, color=color, edgecolor=SURFACE, linewidth=2)
            ax.text(p + 0.4, i + off, f"{val}/{total}", va="center", fontsize=9.5, color=INK)
        if note:
            ax.text(final / total * 100 + 2.6, i - h / 2, "← " + note, va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=10, color=INK)
    ax.set_xlim(0, 26)
    ax.set_xticks([0, 5, 10, 15, 20, 25], ["0%", "5%", "10%", "15%", "20%", "25%"])
    ax.set_title("근거 없는 숫자가 들어간 답의 비율 (할루시네이션 후보)", loc="left", fontsize=13, color=INK, pad=26)
    ax.text(0, 1.03, "답의 숫자가 조회 결과에 없으면 코드가 알려 주고 1번 다시 답하게 함(자기검증)",
            transform=ax.transAxes, fontsize=9, color=INK2)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE_LIGHT), plt.Rectangle((0, 0), 1, 1, color=BLUE_DARK)],
              labels=["검증 전 첫 답", "검증 후 최종 답"], loc="upper center", bbox_to_anchor=(0.45, -0.09), ncol=2, frameon=False, fontsize=9.5,
              labelcolor=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "chart_grounding.png", dpi=200)
    plt.close(fig)


def _box(ax, x, y, w, h, title, sub="", fill="#f3f2ef", edge=GRID, title_color=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor=fill, edgecolor=edge, linewidth=1.2))
    ty = y + h / 2 + (0.13 if sub else 0)
    ax.text(x + w / 2, ty, title, ha="center", va="center", fontsize=11, color=title_color, weight="bold")
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.2, sub, ha="center", va="center", fontsize=8.6, color=INK2)


def _arrow(ax, a, b, color=MUTED, text="", rad=0.0, text_xy=None):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=13, color=color, linewidth=1.4,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if text:
        tx, ty = text_xy or ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.14)
        ax.text(tx, ty, text, ha="center", va="center", fontsize=8.6, color=INK2)


def diagram_flow():
    fig, ax = plt.subplots(figsize=(11, 6.2), facecolor=SURFACE)
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 6.2)
    ax.axis("off")

    # 위: 에이전트가 답하는 과정
    ax.text(0.2, 5.95, "① 에이전트가 답하는 과정", fontsize=12.5, color=INK, weight="bold")
    _box(ax, 0.2, 4.35, 1.7, 1.0, "질문", "\"역삼동에서 제일\n가까운 역은?\"")
    _box(ax, 2.6, 4.35, 2.0, 1.0, "LLM (Gemini)", "어떤 도구를 쓸지 고름", fill="#e6f0fb", edge=BLUE)
    _box(ax, 2.6, 2.75, 2.0, 1.0, "읽기 전용 도구", "run_sql · find_dong", fill="#e6f0fb", edge=BLUE)
    _box(ax, 5.3, 2.75, 1.9, 1.0, "공개 데이터", "법정동 467 · 역 389")
    _box(ax, 5.3, 4.35, 1.9, 1.0, "자기검증", "답의 숫자가\n조회 결과에 있나?", fill="#fdeee7", edge=ORANGE)
    _box(ax, 8.0, 4.35, 2.7, 1.0, "최종 답", "조회 결과에 있는 값만")
    _arrow(ax, (1.9, 4.85), (2.6, 4.85))
    _arrow(ax, (3.35, 4.35), (3.35, 3.75), text="도구 호출 요청", text_xy=(2.75, 4.05))
    _arrow(ax, (3.85, 3.75), (3.85, 4.35), text="결과", text_xy=(4.15, 4.05))
    _arrow(ax, (4.6, 3.25), (5.3, 3.25), text="SELECT만")
    _arrow(ax, (4.6, 4.85), (5.3, 4.85), text="답 초안")
    _arrow(ax, (7.2, 4.85), (8.0, 4.85), text="통과")
    _arrow(ax, (6.25, 5.35), (3.6, 5.35), color=ORANGE, rad=0.35, text="근거 없는 숫자 → 1번 다시 답하기",
           text_xy=(4.9, 5.95))

    # 아래: 채점 과정
    ax.text(0.2, 2.2, "② 정답률을 재는 과정", fontsize=12.5, color=INK, weight="bold")
    _box(ax, 0.2, 0.55, 1.9, 1.1, "질문 세트", "250문항\n(직접 + 다른 AI)")
    _box(ax, 2.8, 1.05, 2.4, 0.75, "에이전트 답", "위 ①의 과정")
    _box(ax, 2.8, 0.15, 2.4, 0.75, "정답 (코드로 계산)", "pandas · 에이전트와 다른 경로")
    _box(ax, 5.9, 0.55, 2.0, 1.1, "규칙 채점", "숫자·이름 대조\n(LLM 판정 없음)")
    _box(ax, 8.6, 0.55, 2.1, 1.1, "정답률 + 사람 검토", "오답·애매한 답은\n직접 읽음")
    _arrow(ax, (2.1, 1.25), (2.8, 1.42))
    _arrow(ax, (2.1, 0.95), (2.8, 0.52))
    _arrow(ax, (5.2, 1.42), (5.9, 1.25))
    _arrow(ax, (5.2, 0.52), (5.9, 0.95))
    _arrow(ax, (7.9, 1.1), (8.6, 1.1))

    fig.tight_layout()
    fig.savefig(OUT / "diagram_flow.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    chart_accuracy()
    chart_grounding()
    diagram_flow()
    print("saved:", ", ".join(p.name for p in sorted(OUT.glob("chart_*.png")) + [OUT / "diagram_flow.png"]))
