"""BPC 4 联图：matplotlib 渲染为 SVG 字符串，供 Jinja 模板内联。

策略：复用旧 charts.py 的曲线绘制逻辑（峰值高亮、阈值高亮、多系统叠加），
只把"输出 PNG"换成"输出 SVG 字符串"。SVG 在 HTML 里随浏览器布局自动缩放。
"""
from __future__ import annotations

from io import StringIO
from math import nan
from typing import Callable, Optional

import matplotlib.pyplot as plt
from matplotlib import gridspec

from big_data_model.incident.features import BpcSystemFeatures, FeatureBag

# --- palette（与 dashboard.css 保持一致） --------------------------------
BG = "#161b22"
PANEL = "#161b22"
PANEL_EDGE = "#30363d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#3fb950"
YELLOW = "#d29922"
ORANGE = "#fb8500"
RED = "#f85149"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
CYAN = "#39c5cf"

SYSTEM_COLORS = [BLUE, ORANGE, GREEN, PURPLE, CYAN, YELLOW]

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _style(ax, title: str, subtitle: str = "") -> None:
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values():
        sp.set_color(PANEL_EDGE)
        sp.set_linewidth(1)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.set_title(title, color=TEXT, fontsize=12, fontweight="bold",
                 loc="left", pad=24)
    if subtitle:
        ax.text(0, 1.04, subtitle, transform=ax.transAxes,
                color=MUTED, fontsize=8, ha="left", va="bottom")
    ax.grid(True, color=PANEL_EDGE, linestyle="--", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)


def _hm(ts: str) -> str:
    return ts[-8:-3] if len(ts) >= 8 else ts


def _draw_metric(
    ax, systems: list[BpcSystemFeatures], metric: str,
    single_color: str, title: str, subtitle: str, unit: str = "",
    highlight: Optional[str] = None,
    worst_picker: Optional[Callable[[BpcSystemFeatures], float]] = None,
    gate: Optional[Callable[[BpcSystemFeatures], bool]] = None,
    annot_fmt: str = "{v:.0f}",
    ylim: Optional[tuple] = None,
) -> None:
    multi = len(systems) > 1
    all_ts = sorted({p.timestamp for s in systems for p in s.timepoints})
    ts_to_x = {ts: i for i, ts in enumerate(all_ts)}
    labels = [_hm(ts) for ts in all_ts]

    for idx, sys in enumerate(systems):
        color = SYSTEM_COLORS[idx % len(SYSTEM_COLORS)] if multi else single_color
        x = [ts_to_x[p.timestamp] for p in sys.timepoints]
        # None values render as gaps (NaN breaks the line and skips the marker)
        # rather than being silently backfilled to 0.
        y = [
            (nan if getattr(p, metric) is None else getattr(p, metric))
            for p in sys.timepoints
        ]
        ax.plot(x, y, color=color, linewidth=1.8 if multi else 2.0,
                marker="o", markersize=3.5 if multi else 4.5,
                markerfacecolor=color, markeredgecolor=BG, markeredgewidth=0.8,
                label=sys.system_name if multi else None)
        if not multi:
            real_y = [v for v in y if v == v]  # drop NaN
            if real_y:
                ax.fill_between(x, y, min(real_y), color=color, alpha=0.12)

    if highlight and worst_picker:
        target = max(systems, key=worst_picker)
        if gate is None or gate(target):
            valid_pts = [
                p for p in target.timepoints if getattr(p, metric) is not None
            ]
            if valid_pts:
                x = [ts_to_x[p.timestamp] for p in valid_pts]
                y = [getattr(p, metric) for p in valid_pts]
                if highlight == "max":
                    i = max(range(len(y)), key=lambda k: y[k])
                    hcolor, dy = RED, 8
                else:
                    i = min(range(len(y)), key=lambda k: y[k])
                    hcolor, dy = ORANGE, -12
                ax.scatter([x[i]], [y[i]], color=hcolor, s=90, zorder=5,
                           edgecolor=BG, linewidth=1.2)
                tag = annot_fmt.format(v=y[i]) + unit
                if multi:
                    tag += f"  {target.system_name}"
                ax.annotate(tag, (x[i], y[i]),
                            textcoords="offset points", xytext=(6, dy),
                            color=hcolor, fontsize=9, fontweight="bold")

    ax.set_xticks(list(range(len(all_ts))))
    ax.set_xticklabels(labels, rotation=0, fontsize=7)
    if ylim is not None:
        ax.set_ylim(bottom=ylim[0], top=ylim[1])
    _style(ax, title, subtitle)
    # 多系统时不在每张图里画图例——4 张图共用同一套"系统→颜色"映射，
    # 逐图重复会挤占绘图区、遮挡曲线。统一映射由 bpc_legend() 暴露，
    # 在 HTML 面板头部展示一次（见 templates/bpc.html.j2）。


def _subtitle(
    systems: list[BpcSystemFeatures],
    single_fmt: Callable[[BpcSystemFeatures], str],
    worst_picker: Callable[[BpcSystemFeatures], float],
    worst_fmt: Callable[[BpcSystemFeatures], str],
) -> str:
    if len(systems) == 1:
        return single_fmt(systems[0])
    worst = max(systems, key=worst_picker)
    return f"{len(systems)} 个系统 · 最差 {worst.system_name} · {worst_fmt(worst)}"


def bpc_legend(bag: FeatureBag) -> list[tuple[str, str]]:
    """系统名 → 曲线颜色 的映射，供模板在面板头部统一展示一次。

    与 ``_draw_metric`` 里的取色规则保持一致（多系统按 ``SYSTEM_COLORS``
    循环取色）。单系统时各图用单色、无需图例，返回空列表。
    """
    if not bag.bpc or not bag.bpc.systems or len(bag.bpc.systems) <= 1:
        return []
    return [
        (s.system_name, SYSTEM_COLORS[idx % len(SYSTEM_COLORS)])
        for idx, s in enumerate(bag.bpc.systems)
    ]


def render_bpc_svg(bag: FeatureBag) -> Optional[str]:
    """渲染 BPC 2×2 联图为 SVG 字符串。无数据返回 None。"""
    if not bag.bpc or not bag.bpc.systems:
        return None
    systems = bag.bpc.systems

    fig = plt.figure(figsize=(14, 5.2), facecolor=BG)
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.55, wspace=0.20,
                           left=0.05, right=0.98, top=0.92, bottom=0.10)

    # trans_count
    ax = fig.add_subplot(gs[0, 0])
    if len(systems) == 1:
        s = systems[0]
        last_str = "—（空值）" if s.trans_count_last is None else str(s.trans_count_last)
        trans_sub = (f"基线 ~{s.trans_count_baseline:.0f} · "
                     f"最末 {last_str}（采集窗口可能未满）")
    else:
        trans_sub = f"{len(systems)} 个系统 · 各自基线见图例"
    _draw_metric(ax, systems, "trans_count", BLUE,
                 "交易笔数 trans_count", trans_sub, unit=" 笔",
                 ylim=(0, None))

    # succ_rate
    ax = fig.add_subplot(gs[0, 1])
    _draw_metric(
        ax, systems, "succ_rate_pct", GREEN,
        "成功率 succ_rate",
        _subtitle(systems,
                  lambda s: f"基线 {s.succ_rate_baseline_pct:.2f}% · "
                            f"最低 {s.succ_rate_min_pct:.2f}% @ {_hm(s.succ_rate_min_ts)}",
                  lambda s: s.succ_rate_baseline_pct - s.succ_rate_min_pct,
                  lambda s: f"最低 {s.succ_rate_min_pct:.2f}% @ {_hm(s.succ_rate_min_ts)}"),
        unit="%", highlight="min",
        worst_picker=lambda s: s.succ_rate_baseline_pct - s.succ_rate_min_pct,
        gate=lambda s: (s.succ_rate_baseline_pct - s.succ_rate_min_pct) > 0.1,
        annot_fmt="{v:.2f}", ylim=(0, 100),
    )

    # duration
    ax = fig.add_subplot(gs[1, 0])
    _draw_metric(
        ax, systems, "duration_ms", ORANGE,
        "平均耗时 duration",
        _subtitle(systems,
                  lambda s: f"基线 {s.duration_baseline_ms:.0f}ms · "
                            f"峰值 {s.duration_max_ms:.0f}ms @ {_hm(s.duration_max_ts)} · "
                            f"偏离 ×{s.duration_deviation_x:.1f}",
                  lambda s: s.duration_deviation_x,
                  lambda s: f"峰值 {s.duration_max_ms:.0f}ms @ {_hm(s.duration_max_ts)} · "
                            f"偏离 ×{s.duration_deviation_x:.1f}"),
        unit="ms", highlight="max",
        worst_picker=lambda s: s.duration_deviation_x,
        gate=lambda s: s.duration_deviation_x >= 2,
        annot_fmt="{v:.0f}", ylim=(0, None),
    )

    # rr_rate
    ax = fig.add_subplot(gs[1, 1])
    _draw_metric(
        ax, systems, "rr_rate_pct", PURPLE,
        "响应率 rr_rate",
        _subtitle(systems,
                  lambda s: f"基线 {s.rr_rate_baseline_pct:.2f}% · "
                            f"最低 {s.rr_rate_min_pct:.2f}% @ {_hm(s.rr_rate_min_ts)}",
                  lambda s: s.rr_rate_baseline_pct - s.rr_rate_min_pct,
                  lambda s: f"最低 {s.rr_rate_min_pct:.2f}% @ {_hm(s.rr_rate_min_ts)}"),
        unit="%", highlight="min",
        worst_picker=lambda s: s.rr_rate_baseline_pct - s.rr_rate_min_pct,
        gate=lambda s: (s.rr_rate_baseline_pct - s.rr_rate_min_pct) > 0.3,
        annot_fmt="{v:.2f}", ylim=(0, 100),
    )

    buf = StringIO()
    fig.savefig(buf, format="svg", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue()
    # 去掉 matplotlib 默认 <?xml ?> 与 <!DOCTYPE>，留下纯 <svg>，便于内联
    if "<svg" in svg:
        svg = svg[svg.index("<svg"):]
    return svg
