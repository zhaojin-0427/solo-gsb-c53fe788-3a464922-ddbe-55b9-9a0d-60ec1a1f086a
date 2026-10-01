"""相接镜头切点回归用例。

场景：镜头 [0,1200)、[1200,2400) 与 900–1300ms 的字幕。
  - 原字幕跨越 1200ms 切点 → 必须标记跨镜头，与平移容差无关；
  - 容差 200ms：唯一最优提案是整体左移到 800–1200ms（移动 100ms），
    绝不能给出“原位 900–1300ms 且可采纳”的跨界提案；
  - 容差 50ms：无可采纳提案，cue 进入冲突链。
恰在切点结束（…1200）或恰在切点开始（1200…）都不算跨镜头。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 无 regex / fastapi 环境下，为纯逻辑测试提供最小 regex 桩
try:  # pragma: no cover
    import regex  # noqa: F401
except ModuleNotFoundError:
    _stub = types.ModuleType("regex")

    class _Pat:
        def __init__(self, p):
            self.p = p

        def findall(self, s):
            if self.p == r"\X":
                return list(s)
            import re
            return re.findall(self.p, s)

        def sub(self, repl, s):
            import re
            return re.sub(self.p, repl, s)

    _stub.compile = lambda p, *a, **k: _Pat(p)
    sys.modules["regex"] = _stub

from app.analysis import build_analysis
from app.corrector import (
    CueInput,
    fits_in_shot,
    shot_windows,
    validate_shift,
)
from app.shots import Shot
from app.subtitles import ParsedCue

SHOTS = [(0, 1200), (1200, 2400)]
SHOT_OBJS = [Shot(ord=1, start_ms=0, end_ms=1200),
             Shot(ord=2, start_ms=1200, end_ms=2400)]


def _cue(cid="c1", start=900, end=1300):
    return ParsedCue(cue_id=cid, ord=1, start_ms=start, end_ms=end,
                     raw_text="hello", graphemes=5, raw_hash="deadbeef")


def test_each_shot_independent_no_merge():
    cue = CueInput("c1", 1, 1100, 1300, 1)   # 时长 200，跨越 1200
    wins = shot_windows(cue, SHOTS, 200, 5000)
    # 两个镜头各自贡献窗口，切点 1200 处不允许出现跨界起点
    assert [(w.lo, w.hi) for w in wins] == [(900, 1000), (1200, 1300)]
    for w in wins:
        assert w.lo + cue.duration <= 1200 or w.lo >= 1200


def test_fits_boundary_endpoints():
    assert fits_in_shot(800, 1200, SHOTS)      # 恰在切点结束 → 允许
    assert fits_in_shot(1200, 1600, SHOTS)     # 恰在切点开始 → 允许
    assert fits_in_shot(0, 1200, SHOTS)
    assert not fits_in_shot(900, 1300, SHOTS)  # 跨越切点 → 跨镜头


def test_cross_shot_flag_independent_of_tolerance():
    for tol in (200, 50, 0):
        res = build_analysis([_cue()], SHOT_OBJS, 100.0, 0, tol)
        rep = res.cues[0]
        assert rep.cross_shot is True, tol
        assert res.stats["cross_shot_count"] == 1


def test_tolerance_200_proposes_shift_to_800_1200():
    res = build_analysis([_cue()], SHOT_OBJS, 100.0, 0, 200)
    rep = res.cues[0]
    assert (rep.proposal_start_ms, rep.proposal_end_ms) == (800, 1200)
    assert rep.proposal_start_ms != rep.start_ms
    assert res.chains == []
    assert res.stats["proposal_count"] == 1
    assert res.stats["total_shift_ms"] == 100
    # 原位是跨界位置，校验必须拒绝
    assert validate_shift(900, 1300, 900, 1300, SHOTS, 200) is not None
    # 提案位置合法
    assert validate_shift(800, 1200, 900, 1300, SHOTS, 200) is None


def test_tolerance_50_no_adoptable_proposal_and_chain():
    res = build_analysis([_cue()], SHOT_OBJS, 100.0, 0, 50)
    rep = res.cues[0]
    assert rep.proposal_start_ms is None
    assert rep.proposal_end_ms is None
    assert res.stats["proposal_count"] == 0
    assert len(res.chains) == 1
    assert res.chains[0]["cue_ids"] == ["c1"]
    assert any(i["cue_id"] == "c1" for i in res.intrinsic)


def test_validate_shift_rules():
    assert validate_shift(840, 1240, 900, 1300, SHOTS, 200) is not None  # 跨切点
    assert validate_shift(700, 1100, 900, 1300, SHOTS, 200) is None      # 整体在前一镜头
    assert validate_shift(700, 1100, 900, 1300, SHOTS, 50) is not None   # 超出容差
    assert validate_shift(800, 1201, 900, 1300, SHOTS, 200) is not None  # 改了时长
    assert validate_shift(1200, 1600, 900, 1300, SHOTS, 300) is None     # 落入后一镜头
    assert validate_shift(900, 1300, 900, 1300, [], 200) is None         # 无镜头不校验镜头


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"shot-boundary regression: {len(fns)} cases passed")


if __name__ == "__main__":
    main()
