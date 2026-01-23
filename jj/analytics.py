"""Analytics and insights for Job Journal."""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from jj.db import get_connection, DB_PATH


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
        screening = counts.get('screening', 0)
        interview = counts.get('interview', 0)
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
                    'name': 'Screening',
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


def get_time_in_stage_stats() -> dict[str, Any]:
    """Get average time spent in each stage."""
    if not DB_PATH.exists():
        return {}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Average days in each status
        cursor.execute("""
            SELECT
                status,
                ROUND(AVG(julianday(COALESCE(updated_at, 'now')) - julianday(applied_at)), 1) as avg_days,
                MIN(julianday(COALESCE(updated_at, 'now')) - julianday(applied_at)) as min_days,
                MAX(julianday(COALESCE(updated_at, 'now')) - julianday(applied_at)) as max_days,
                COUNT(*) as count
            FROM applications
            WHERE status NOT IN ('skipped', 'prospect')
              AND applied_at IS NOT NULL
            GROUP BY status
        """)

        stats = {}
        for row in cursor.fetchall():
            stats[row['status']] = {
                'avg_days': row['avg_days'] or 0,
                'min_days': row['min_days'] or 0,
                'max_days': row['max_days'] or 0,
                'count': row['count'],
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


def get_all_analytics() -> dict[str, Any]:
    """Get all analytics data for the dashboard."""
    return {
        'funnel': get_funnel_stats(),
        'time_in_stage': get_time_in_stage_stats(),
        'timeline': get_application_timeline(30),
        'response_rates': get_company_response_rates()[:10],
        'fit_score_analysis': get_fit_score_analysis(),
        'rejection_patterns': get_rejection_patterns(),
        'timing_insights': get_timing_insights(),
        'weekly_summary': get_weekly_summary(4),
    }
