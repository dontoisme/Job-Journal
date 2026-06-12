"""Analytics and insights for Job Journal."""

from datetime import date, datetime, timedelta
from typing import Any, Optional

from jj.db import DB_PATH, get_connection

# Evidence union for the funnel summary: every (stage, app, timestamp) signal
# that an application reached a stage, from applications, real (non-migration)
# status events, interview_round events, and paired resolution emails.
_FUNNEL_EVIDENCE_SQL = """
    SELECT 'applications' AS stage, id AS app_id, applied_at AS ts
    FROM applications
    WHERE applied_at IS NOT NULL AND status NOT IN ('prospect', 'skipped')

    UNION ALL
    SELECT
        CASE
            WHEN json_extract(new_value, '$.status') IN ('recruiter_screen', 'hiring_manager', 'screening') THEN 'calls'
            WHEN json_extract(new_value, '$.status') IN ('interview', 'technical') THEN 'interviews'
            WHEN json_extract(new_value, '$.status') = 'offer' THEN 'offers'
        END AS stage,
        entity_id AS app_id,
        COALESCE(json_extract(metadata, '$.date'), created_at) AS ts
    FROM events
    WHERE event_type = 'status_change'
      AND entity_type = 'application'
      AND COALESCE(json_extract(metadata, '$.source'), '') != 'migration'
      AND json_extract(new_value, '$.status') IN
          ('recruiter_screen', 'hiring_manager', 'screening', 'interview', 'technical', 'offer')

    UNION ALL
    SELECT 'interviews' AS stage, entity_id AS app_id,
           COALESCE(json_extract(metadata, '$.date'), created_at) AS ts
    FROM events
    WHERE event_type = 'interview_round' AND entity_type = 'application'

    UNION ALL
    SELECT
        CASE resolution_type
            WHEN 'screening' THEN 'calls'
            WHEN 'interview' THEN 'interviews'
            WHEN 'offer' THEN 'offers'
        END AS stage,
        application_id AS app_id,
        received_at AS ts
    FROM application_emails
    WHERE resolution_type IN ('screening', 'interview', 'offer')
"""

FUNNEL_STAGES = [
    ('applications', 'Applications'),
    ('calls', 'Calls'),
    ('interviews', 'Interviews'),
    ('offers', 'Offers'),
]


def _parse_evidence_date(ts: str) -> Optional[date]:
    """Parse a date or ISO datetime string to a date."""
    try:
        return date.fromisoformat(str(ts)[:10])
    except ValueError:
        return None


def get_funnel_summary(trail_weeks: int = 12, trail_months: int = 6) -> dict[str, Any]:
    """Answer "how many applications, calls, and interviews have I had?"

    Counts distinct applications per stage from the evidence union. All-time
    counts an app once per stage; period counts include any app with evidence
    in that period (so a second interview round this week counts this week).
    Weeks run Sunday-Saturday to match TWC.
    """
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_FUNNEL_EVIDENCE_SQL)
        rows = [
            (row['stage'], row['app_id'], row['ts'])
            for row in cursor.fetchall()
            if row['stage'] and row['app_id'] and row['ts']
        ]

    today = datetime.now().date()
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    month_start = today.replace(day=1)

    stage_keys = [key for key, _ in FUNNEL_STAGES]
    all_time = {key: set() for key in stage_keys}
    this_week = {key: set() for key in stage_keys}
    this_month = {key: set() for key in stage_keys}
    by_week: dict[str, dict[str, set]] = {}
    by_month: dict[str, dict[str, set]] = {}

    for stage, app_id, ts in rows:
        if stage not in all_time:
            continue
        all_time[stage].add(app_id)
        d = _parse_evidence_date(ts)
        if d is None or d > today:
            continue
        if d >= week_start:
            this_week[stage].add(app_id)
        if d >= month_start:
            this_month[stage].add(app_id)
        evidence_week = (d - timedelta(days=(d.weekday() + 1) % 7)).isoformat()
        by_week.setdefault(evidence_week, {k: set() for k in stage_keys})[stage].add(app_id)
        by_month.setdefault(d.strftime('%Y-%m'), {k: set() for k in stage_keys})[stage].add(app_id)

    stages = [
        {
            'key': key,
            'label': label,
            'all_time': len(all_time[key]),
            'this_week': len(this_week[key]),
            'this_month': len(this_month[key]),
        }
        for key, label in FUNNEL_STAGES
    ]

    def _trail(buckets: dict[str, dict[str, set]], labels: list[str], label_field: str) -> list[dict[str, Any]]:
        trail = []
        for label in labels:
            counts = buckets.get(label, {})
            entry: dict[str, Any] = {label_field: label}
            for key in stage_keys:
                entry[key] = len(counts.get(key, set()))
            trail.append(entry)
        return trail

    week_labels = [
        (week_start - timedelta(weeks=i)).isoformat()
        for i in range(trail_weeks - 1, -1, -1)
    ]
    month_labels = []
    year, month = month_start.year, month_start.month
    for _ in range(trail_months):
        month_labels.append(f'{year:04d}-{month:02d}')
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_labels.reverse()

    conversions = {}
    pairs = [('applications', 'calls'), ('calls', 'interviews'), ('interviews', 'offers')]
    for upstream, downstream in pairs:
        if all_time[upstream]:
            conversions[f'{upstream}_to_{downstream}'] = round(
                len(all_time[downstream]) / len(all_time[upstream]) * 100, 1
            )

    return {
        'stages': stages,
        'weeks': _trail(by_week, week_labels, 'week_start'),
        'months': _trail(by_month, month_labels, 'month'),
        'conversion_rates': conversions,
        'week_start': week_start.isoformat(),
        'month_start': month_start.isoformat(),
    }


def get_funnel_stats() -> dict[str, Any]:
    """Get conversion funnel statistics."""
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get counts by status
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM applications
            WHERE status NOT IN ('skipped', 'prospect')
            GROUP BY status
        """)

        counts = {row['status']: row['count'] for row in cursor.fetchall()}

        # Calculate conversion rates
        applied = counts.get('applied', 0)
        # Calls bucket: recruiter/HM screens (legacy 'screening' rows included)
        screening = (
            counts.get('recruiter_screen', 0)
            + counts.get('hiring_manager', 0)
            + counts.get('screening', 0)
        )
        interview = counts.get('interview', 0) + counts.get('technical', 0)
        offer = counts.get('offer', 0)
        rejected = counts.get('rejected', 0)

        total_active = applied + screening + interview + offer + rejected

        funnel = {
            'stages': [
                {
                    'name': 'Applied',
                    'count': applied + screening + interview + offer,
                    'color': '#3b82f6',
                },
                {
                    'name': 'Calls',
                    'count': screening + interview + offer,
                    'color': '#8b5cf6',
                },
                {
                    'name': 'Interview',
                    'count': interview + offer,
                    'color': '#f59e0b',
                },
                {
                    'name': 'Offer',
                    'count': offer,
                    'color': '#10b981',
                },
            ],
            'rejected': rejected,
            'total': total_active,
            'conversion_rates': {},
        }

        # Calculate conversion rates between stages
        if total_active > 0:
            total_entered = applied + screening + interview + offer
            if total_entered > 0:
                funnel['conversion_rates']['applied_to_screening'] = round(
                    (screening + interview + offer) / total_entered * 100, 1
                )
            if screening + interview + offer > 0:
                funnel['conversion_rates']['screening_to_interview'] = round(
                    (interview + offer) / (screening + interview + offer) * 100, 1
                )
            if interview + offer > 0:
                funnel['conversion_rates']['interview_to_offer'] = round(
                    offer / (interview + offer) * 100, 1
                )
            funnel['conversion_rates']['overall'] = round(
                offer / total_entered * 100, 1
            ) if total_entered > 0 else 0

        return funnel


def _parse_evidence_datetime(ts: str) -> Optional[datetime]:
    """Parse an ISO datetime (or date) string, dropping timezone info."""
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '')).replace(tzinfo=None)
    except ValueError:
        return None


def get_time_in_stage_stats() -> dict[str, Any]:
    """Get time spent in each stage, derived from status_change events.

    Duration in a stage runs from the timestamp that entered it (applied_at
    for the first stage) to the event that left it; the current stage is
    still open and measured to now. Migration snapshot events are excluded.
    """
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT entity_id, created_at,
                   json_extract(old_value, '$.status') as old_status,
                   json_extract(new_value, '$.status') as new_status
            FROM events
            WHERE event_type = 'status_change'
              AND entity_type = 'application'
              AND COALESCE(json_extract(metadata, '$.source'), '') != 'migration'
            ORDER BY entity_id, created_at
        """)
        event_rows = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT id, applied_at FROM applications")
        applied_at = {row['id']: row['applied_at'] for row in cursor.fetchall()}

    by_app: dict[int, list[dict]] = {}
    for row in event_rows:
        by_app.setdefault(row['entity_id'], []).append(row)

    now = datetime.now()
    durations: dict[str, list[float]] = {}

    def _record(status: Optional[str], start: Optional[datetime], end: Optional[datetime]) -> None:
        if not status or status in ('skipped', 'prospect') or not start or not end:
            return
        days = (end - start).total_seconds() / 86400
        if days >= 0:
            durations.setdefault(status, []).append(days)

    for app_id, app_events in by_app.items():
        prev_ts = _parse_evidence_datetime(applied_at.get(app_id) or '')
        for event in app_events:
            ts = _parse_evidence_datetime(event['created_at'])
            _record(event['old_status'], prev_ts, ts)
            prev_ts = ts or prev_ts
        # Current stage is still open
        _record(app_events[-1]['new_status'], prev_ts, now)

    stats = {}
    for status, days_list in durations.items():
        stats[status] = {
            'avg_days': round(sum(days_list) / len(days_list), 1),
            'min_days': round(min(days_list), 1),
            'max_days': round(max(days_list), 1),
            'count': len(days_list),
        }

    return stats


def get_application_timeline(days: int = 30) -> list[dict[str, Any]]:
    """Get application activity over time."""
    if not DB_PATH.exists():
        return []

    with get_connection() as conn:
        cursor = conn.cursor()

        # Applications per day
        cursor.execute("""
            SELECT
                date(applied_at) as date,
                COUNT(*) as applications,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejections,
                SUM(CASE WHEN status = 'interview' THEN 1 ELSE 0 END) as interviews,
                SUM(CASE WHEN status = 'offer' THEN 1 ELSE 0 END) as offers
            FROM applications
            WHERE applied_at IS NOT NULL
              AND applied_at >= date('now', ?)
            GROUP BY date(applied_at)
            ORDER BY date(applied_at)
        """, (f'-{days} days',))

        return [dict(row) for row in cursor.fetchall()]


def get_company_response_rates() -> list[dict[str, Any]]:
    """Analyze response rates by company."""
    if not DB_PATH.exists():
        return []

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                company,
                COUNT(*) as total_applications,
                SUM(CASE WHEN email_confirmed = 1 THEN 1 ELSE 0 END) as confirmed,
                SUM(CASE WHEN status IN ('screening', 'interview', 'offer') THEN 1 ELSE 0 END) as progressed,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                AVG(CASE
                    WHEN confirmed_at IS NOT NULL AND applied_at IS NOT NULL
                    THEN julianday(confirmed_at) - julianday(applied_at)
                    ELSE NULL
                END) as avg_response_days
            FROM applications
            WHERE status NOT IN ('skipped', 'prospect')
            GROUP BY company
            HAVING total_applications >= 1
            ORDER BY total_applications DESC
        """)

        results = []
        for row in cursor.fetchall():
            results.append({
                'company': row['company'],
                'total': row['total_applications'],
                'confirmed': row['confirmed'],
                'progressed': row['progressed'],
                'rejected': row['rejected'],
                'response_rate': round(row['confirmed'] / row['total_applications'] * 100, 1) if row['total_applications'] > 0 else 0,
                'progress_rate': round(row['progressed'] / row['total_applications'] * 100, 1) if row['total_applications'] > 0 else 0,
                'avg_response_days': round(row['avg_response_days'], 1) if row['avg_response_days'] else None,
            })

        return results


def get_fit_score_analysis() -> dict[str, Any]:
    """Analyze correlation between fit scores and outcomes."""
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Group applications by fit score ranges
        cursor.execute("""
            SELECT
                CASE
                    WHEN fit_score >= 80 THEN '80-100'
                    WHEN fit_score >= 70 THEN '70-79'
                    WHEN fit_score >= 60 THEN '60-69'
                    WHEN fit_score >= 50 THEN '50-59'
                    ELSE 'Below 50'
                END as score_range,
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('interview', 'offer') THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
            FROM applications
            WHERE fit_score IS NOT NULL
              AND status NOT IN ('skipped', 'prospect')
            GROUP BY score_range
            ORDER BY
                CASE score_range
                    WHEN '80-100' THEN 1
                    WHEN '70-79' THEN 2
                    WHEN '60-69' THEN 3
                    WHEN '50-59' THEN 4
                    ELSE 5
                END
        """)

        ranges = []
        for row in cursor.fetchall():
            success_rate = round(row['success'] / row['total'] * 100, 1) if row['total'] > 0 else 0
            ranges.append({
                'range': row['score_range'],
                'total': row['total'],
                'success': row['success'],
                'rejected': row['rejected'],
                'success_rate': success_rate,
            })

        return {
            'ranges': ranges,
            'recommendation': _get_fit_score_recommendation(ranges),
        }


def _get_fit_score_recommendation(ranges: list) -> str:
    """Generate recommendation based on fit score analysis."""
    if not ranges:
        return "Not enough data for recommendations yet."

    # Find the range with best success rate
    best_range = max(ranges, key=lambda r: r['success_rate']) if ranges else None

    if best_range and best_range['success_rate'] > 0:
        return f"Best results from {best_range['range']} fit scores ({best_range['success_rate']}% success rate). Focus on roles in this range."
    else:
        return "Apply to more roles to build data for personalized recommendations."


def get_rejection_patterns() -> dict[str, Any]:
    """Analyze rejection patterns from email subjects."""
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get rejection emails with timing
        cursor.execute("""
            SELECT
                company,
                position,
                applied_at,
                latest_update_at,
                latest_update_subject,
                ROUND(julianday(latest_update_at) - julianday(applied_at), 0) as days_to_rejection
            FROM applications
            WHERE latest_update_type = 'rejection'
              AND applied_at IS NOT NULL
              AND latest_update_at IS NOT NULL
            ORDER BY latest_update_at DESC
        """)

        rejections = [dict(row) for row in cursor.fetchall()]

        # Analyze timing
        if rejections:
            days_list = [r['days_to_rejection'] for r in rejections if r['days_to_rejection']]
            avg_days = sum(days_list) / len(days_list) if days_list else 0

            # Group by timing
            quick = len([d for d in days_list if d <= 3])
            standard = len([d for d in days_list if 3 < d <= 14])
            delayed = len([d for d in days_list if d > 14])

            timing = {
                'avg_days': round(avg_days, 1),
                'quick_rejections': quick,  # Within 3 days (likely automated)
                'standard_rejections': standard,  # 4-14 days
                'delayed_rejections': delayed,  # Over 14 days
            }
        else:
            timing = {'avg_days': 0, 'quick_rejections': 0, 'standard_rejections': 0, 'delayed_rejections': 0}

        return {
            'recent_rejections': rejections[:10],
            'timing': timing,
            'total': len(rejections),
        }


def get_timing_insights() -> dict[str, Any]:
    """Analyze best times to apply."""
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Applications by day of week
        cursor.execute("""
            SELECT
                CASE strftime('%w', applied_at)
                    WHEN '0' THEN 'Sunday'
                    WHEN '1' THEN 'Monday'
                    WHEN '2' THEN 'Tuesday'
                    WHEN '3' THEN 'Wednesday'
                    WHEN '4' THEN 'Thursday'
                    WHEN '5' THEN 'Friday'
                    WHEN '6' THEN 'Saturday'
                END as day_of_week,
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('screening', 'interview', 'offer') THEN 1 ELSE 0 END) as progressed,
                SUM(CASE WHEN email_confirmed = 1 THEN 1 ELSE 0 END) as confirmed
            FROM applications
            WHERE applied_at IS NOT NULL
              AND status NOT IN ('skipped', 'prospect')
            GROUP BY strftime('%w', applied_at)
            ORDER BY strftime('%w', applied_at)
        """)

        by_day = []
        for row in cursor.fetchall():
            if row['day_of_week']:
                by_day.append({
                    'day': row['day_of_week'],
                    'total': row['total'],
                    'progressed': row['progressed'],
                    'success_rate': round(row['progressed'] / row['total'] * 100, 1) if row['total'] > 0 else 0,
                    'response_rate': round(row['confirmed'] / row['total'] * 100, 1) if row['total'] > 0 else 0,
                })

        # Find best day
        best_day = max(by_day, key=lambda d: d['success_rate']) if by_day else None

        return {
            'by_day': by_day,
            'best_day': best_day['day'] if best_day else None,
            'recommendation': f"Best results on {best_day['day']} ({best_day['success_rate']}% success rate)" if best_day and best_day['success_rate'] > 0 else "Apply to more roles to identify optimal timing.",
        }


def get_weekly_summary(weeks: int = 4) -> list[dict[str, Any]]:
    """Get weekly activity summary."""
    if not DB_PATH.exists():
        return []

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                strftime('%Y-W%W', applied_at) as week,
                COUNT(*) as applications,
                SUM(CASE WHEN email_confirmed = 1 THEN 1 ELSE 0 END) as confirmations,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejections,
                SUM(CASE WHEN status IN ('interview', 'offer') THEN 1 ELSE 0 END) as advances
            FROM applications
            WHERE applied_at IS NOT NULL
              AND applied_at >= date('now', ?)
            GROUP BY strftime('%Y-W%W', applied_at)
            ORDER BY week DESC
        """, (f'-{weeks * 7} days',))

        return [dict(row) for row in cursor.fetchall()]


def get_all_analytics(days: int = 30) -> dict[str, Any]:
    """Get all analytics data for the dashboard.

    Args:
        days: Window for time-bounded sections (timeline, weekly summary).
    """
    weeks = max(4, min(days // 7, 52))
    return {
        'funnel': get_funnel_stats(),
        'funnel_summary': get_funnel_summary(),
        'event_funnel': get_event_conversion_funnel(),
        'time_in_stage': get_time_in_stage_stats(),
        'timeline': get_application_timeline(days),
        'response_rates': get_company_response_rates()[:10],
        'fit_score_analysis': get_fit_score_analysis(),
        'rejection_patterns': get_rejection_patterns(),
        'timing_insights': get_timing_insights(),
        'weekly_summary': get_weekly_summary(weeks),
        'stage_progression': get_stage_progression_stats(),
        'window_days': days,
    }


# Event-based analytics for application lifecycle tracking

def get_stage_progression_stats() -> dict[str, Any]:
    """
    Count unique applications that reached each stage using the events table.

    This provides accurate historical data about how many applications
    made it to each stage, regardless of current status.
    """
    from jj.db import STATUS_ORDER

    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get unique applications that reached each status via events.
        # Excludes source='migration' events: those are a one-time snapshot of
        # current status at migration time, not real progressions, and some
        # were later corrected without new events.
        cursor.execute("""
            SELECT
                json_extract(new_value, '$.status') as status,
                COUNT(DISTINCT entity_id) as unique_apps
            FROM events
            WHERE event_type = 'status_change'
              AND entity_type = 'application'
              AND json_extract(new_value, '$.status') IS NOT NULL
              AND COALESCE(json_extract(metadata, '$.source'), '') != 'migration'
            GROUP BY json_extract(new_value, '$.status')
        """)

        reached = {}
        for row in cursor.fetchall():
            status = row['status']
            if status and status not in ('skipped', 'prospect'):
                reached[status] = row['unique_apps']

        # Also check current status for apps without (non-migration) event
        # history, so migration-only apps still count by current status.
        cursor.execute("""
            SELECT status, COUNT(DISTINCT id) as count
            FROM applications
            WHERE status NOT IN ('skipped', 'prospect')
              AND id NOT IN (
                  SELECT DISTINCT entity_id FROM events
                  WHERE event_type = 'status_change' AND entity_type = 'application'
                    AND COALESCE(json_extract(metadata, '$.source'), '') != 'migration'
              )
            GROUP BY status
        """)

        for row in cursor.fetchall():
            status = row['status']
            if status:
                reached[status] = reached.get(status, 0) + row['count']

        # Order by lifecycle progression
        ordered = []
        for status in ['applied', 'recruiter_screen', 'screening', 'hiring_manager',
                       'interview', 'technical', 'offer', 'accepted', 'rejected', 'withdrawn']:
            if status in reached:
                ordered.append({
                    'status': status,
                    'count': reached[status],
                    'order': STATUS_ORDER.get(status, 99),
                })

        return {
            'by_status': reached,
            'ordered': sorted(ordered, key=lambda x: (x['order'] if x['order'] >= 0 else 100, x['status'])),
            'total_tracked': sum(reached.values()),
        }


def get_event_conversion_funnel() -> dict[str, Any]:
    """
    Calculate conversion rates between stages using event history.

    This is more accurate than snapshot-based funnel because it tracks
    actual progressions, not just current states.
    """
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # For each application, find the highest status it reached
        cursor.execute("""
            WITH app_max_status AS (
                SELECT
                    entity_id,
                    json_extract(new_value, '$.status') as status
                FROM events
                WHERE event_type = 'status_change'
                  AND entity_type = 'application'
                  AND json_extract(new_value, '$.status') NOT IN ('skipped', 'prospect', 'rejected', 'withdrawn')
                  AND COALESCE(json_extract(metadata, '$.source'), '') != 'migration'
            ),
            app_highest AS (
                SELECT
                    entity_id,
                    MAX(CASE status
                        WHEN 'applied' THEN 1
                        WHEN 'recruiter_screen' THEN 2
                        WHEN 'screening' THEN 2
                        WHEN 'hiring_manager' THEN 3
                        WHEN 'interview' THEN 4
                        WHEN 'technical' THEN 4
                        WHEN 'offer' THEN 5
                        WHEN 'accepted' THEN 6
                        ELSE 0
                    END) as highest_stage
                FROM app_max_status
                GROUP BY entity_id
            )
            SELECT
                highest_stage,
                COUNT(*) as count
            FROM app_highest
            GROUP BY highest_stage
            ORDER BY highest_stage
        """)

        stage_counts = {}
        for row in cursor.fetchall():
            stage = row['highest_stage']
            stage_counts[stage] = row['count']

        # Calculate cumulative counts (how many reached at least this stage)
        stages = ['applied', 'recruiter_screen', 'hiring_manager', 'interview', 'offer', 'accepted']
        stage_num = {1: 'applied', 2: 'recruiter_screen', 3: 'hiring_manager', 4: 'interview', 5: 'offer', 6: 'accepted'}

        cumulative = {}
        for i in range(1, 7):
            cumulative[stage_num.get(i, 'unknown')] = sum(
                stage_counts.get(j, 0) for j in range(i, 7)
            )

        # Calculate conversion rates
        conversions = {}
        prev_stage = None
        for stage in stages:
            if prev_stage and cumulative.get(prev_stage, 0) > 0:
                rate = cumulative.get(stage, 0) / cumulative.get(prev_stage, 0) * 100
                conversions[f'{prev_stage}_to_{stage}'] = round(rate, 1)
            prev_stage = stage

        return {
            'reached_at_least': cumulative,
            'conversion_rates': conversions,
            'raw_stage_counts': stage_counts,
        }


def get_application_journey(app_id: int) -> list[dict[str, Any]]:
    """
    Get the full status change timeline for a single application.

    Returns chronologically ordered events showing the application's
    journey through the hiring process.
    """
    if not DB_PATH.exists():
        return []

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get application info
        cursor.execute("""
            SELECT company, position, applied_at, created_at, status
            FROM applications WHERE id = ?
        """, (app_id,))
        app = cursor.fetchone()

        if not app:
            return []

        journey = []

        # Add initial application event
        applied_at = app['applied_at'] or app['created_at']
        if applied_at:
            journey.append({
                'timestamp': applied_at,
                'event': 'Application submitted',
                'status': 'applied',
                'source': 'application',
            })

        # Get status change events
        cursor.execute("""
            SELECT
                created_at,
                json_extract(old_value, '$.status') as old_status,
                json_extract(new_value, '$.status') as new_status,
                json_extract(metadata, '$.reason') as reason,
                json_extract(metadata, '$.source') as source
            FROM events
            WHERE entity_type = 'application'
              AND entity_id = ?
              AND event_type = 'status_change'
            ORDER BY created_at
        """, (app_id,))

        for row in cursor.fetchall():
            new_status = row['new_status']
            reason = row['reason'] or ''
            source = row['source'] or 'unknown'

            # Create human-readable event description
            event_desc = f"Status changed to {new_status}"
            if reason:
                event_desc += f" ({reason})"

            journey.append({
                'timestamp': row['created_at'],
                'event': event_desc,
                'old_status': row['old_status'],
                'status': new_status,
                'source': source,
                'reason': reason,
            })

        # Get email events from application_emails
        cursor.execute("""
            SELECT
                received_at,
                email_type,
                resolution_type,
                subject
            FROM application_emails
            WHERE application_id = ?
            ORDER BY received_at
        """, (app_id,))

        for row in cursor.fetchall():
            email_type = row['email_type']
            res_type = row['resolution_type']

            if email_type == 'confirmation':
                event_desc = "Confirmation email received"
            elif email_type == 'resolution':
                event_desc = f"Resolution email: {res_type or 'update'}"
            else:
                event_desc = f"Email: {email_type}"

            journey.append({
                'timestamp': row['received_at'],
                'event': event_desc,
                'email_type': email_type,
                'resolution_type': res_type,
                'subject': row['subject'],
                'source': 'email',
            })

        # Sort by timestamp
        journey.sort(key=lambda x: x.get('timestamp') or '0000-00-00')

        return journey


def get_average_time_between_stages() -> dict[str, Any]:
    """
    Calculate average time between status transitions using event data.
    """
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Get consecutive events for each application
        cursor.execute("""
            WITH ordered_events AS (
                SELECT
                    entity_id,
                    created_at,
                    json_extract(old_value, '$.status') as old_status,
                    json_extract(new_value, '$.status') as new_status,
                    LAG(created_at) OVER (PARTITION BY entity_id ORDER BY created_at) as prev_timestamp
                FROM events
                WHERE event_type = 'status_change'
                  AND entity_type = 'application'
            )
            SELECT
                old_status,
                new_status,
                AVG(julianday(created_at) - julianday(prev_timestamp)) as avg_days,
                COUNT(*) as count
            FROM ordered_events
            WHERE prev_timestamp IS NOT NULL
              AND old_status IS NOT NULL
              AND new_status IS NOT NULL
            GROUP BY old_status, new_status
            HAVING count >= 2
        """)

        transitions = []
        for row in cursor.fetchall():
            transitions.append({
                'from': row['old_status'],
                'to': row['new_status'],
                'avg_days': round(row['avg_days'], 1) if row['avg_days'] else 0,
                'count': row['count'],
            })

        return {
            'transitions': transitions,
            'note': 'Based on applications with event history',
        }
