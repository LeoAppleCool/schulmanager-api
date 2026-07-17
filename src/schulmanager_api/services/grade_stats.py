from __future__ import annotations

from schulmanager_api.models.schemas import GradeItem, GradeStats, SubjectStats

# German grade scale: 1+ (best) to 6 (worst)
_GRADE_VALUES: dict[str, float] = {
    "1+": 0.67, "1": 1.0, "1-": 1.33,
    "2+": 1.67, "2": 2.0, "2-": 2.33,
    "3+": 2.67, "3": 3.0, "3-": 3.33,
    "4+": 3.67, "4": 4.0, "4-": 4.33,
    "5+": 4.67, "5": 5.0, "5-": 5.33,
    "6": 6.0,
}


def _grade_value(grade: str) -> float | None:
    return _GRADE_VALUES.get(grade.strip())


def _trend(values: list[float]) -> str:
    """Compare first vs second half of grades (lower numeric = better grade)."""
    if len(values) < 4:
        return "stable"
    half = len(values) // 2
    early_avg = sum(values[:half]) / half
    late_avg = sum(values[half:]) / (len(values) - half)
    diff = late_avg - early_avg
    if diff < -0.3:
        return "improving"
    if diff > 0.3:
        return "declining"
    return "stable"


def _weight(item: GradeItem) -> float:
    """Positive per-grade weight; defaults to 1.0 when missing or non-positive."""
    w = item.weight
    if w is None or w <= 0:
        return 1.0
    return w


def compute_grade_stats(grades: list[GradeItem]) -> GradeStats:
    by_subject: dict[str, list[GradeItem]] = {}
    for item in grades:
        by_subject.setdefault(item.subject, []).append(item)

    subject_stats: list[SubjectStats] = []
    # (weighted-average, total-weight) per subject, for a globally weighted overall GPA.
    subject_weighted: list[tuple[float, float]] = []
    for subject, items in sorted(by_subject.items()):
        # Sort by date for trend computation
        dated = sorted(items, key=lambda g: g.date.isoformat() if g.date else "")
        pairs = [(v, _weight(item)) for item in dated if (v := _grade_value(item.grade)) is not None]
        if not pairs:
            continue
        values = [v for v, _ in pairs]
        total_weight = sum(w for _, w in pairs)
        avg = sum(v * w for v, w in pairs) / total_weight
        subject_stats.append(
            SubjectStats(
                subject=subject,
                average=round(avg, 2),
                grade_count=len(values),
                trend=_trend(values),
                grade_values=values,
            )
        )
        subject_weighted.append((avg, total_weight))

    if not subject_stats:
        return GradeStats(subjects=[], overall_gpa=None, best_subject=None, worst_subject=None)

    # Overall GPA weighted by each subject's total grade weight (a subject with more/heavier
    # grades counts more), instead of a naive mean-of-means.
    total_w = sum(w for _, w in subject_weighted)
    overall_gpa = round(sum(a * w for a, w in subject_weighted) / total_w, 2)
    best = min(subject_stats, key=lambda s: s.average).subject
    worst = max(subject_stats, key=lambda s: s.average).subject

    return GradeStats(
        subjects=subject_stats,
        overall_gpa=overall_gpa,
        best_subject=best,
        worst_subject=worst,
    )
