from typing import List
from app.schemas.audit import AuditCalculateRequest, AuditReportResponse


class AuditService:
    """Calculates after-hours missed call revenue leakage and competitor defection losses."""

    TRADE_BENCHMARKS = {
        "Plumbing": {"avg_ticket": 750.0, "urgency": "High", "booking_rate": 0.75},
        "HVAC": {"avg_ticket": 1250.0, "urgency": "Severe", "booking_rate": 0.78},
        "Electrical": {"avg_ticket": 680.0, "urgency": "High", "booking_rate": 0.70},
        "Roofing": {"avg_ticket": 2200.0, "urgency": "Moderate", "booking_rate": 0.65},
        "Restoration": {"avg_ticket": 3800.0, "urgency": "Extreme", "booking_rate": 0.82},
    }

    def calculate_leakage(self, req: AuditCalculateRequest) -> AuditReportResponse:
        # Industry benchmark constants (DMV & national contractor research)
        missed_rate = 0.28  # 28% of total calls happen after-hours or when lines are busy
        competitor_switch_rate = 0.65  # 65% of unanswered callers dial the very next contractor on Google
        booking_rate = self.TRADE_BENCHMARKS.get(req.trade, {}).get("booking_rate", 0.72)

        # Compute volume numbers
        missed_call_count = int(round(req.monthly_call_volume * missed_rate))
        lost_jobs_count = max(1, int(round(missed_call_count * competitor_switch_rate * booking_rate)))

        # Dollar calculations
        monthly_leak_revenue = round(lost_jobs_count * req.average_ticket, 2)
        annual_leak_revenue = round(monthly_leak_revenue * 12, 2)
        annual_lost_profit = round(annual_leak_revenue * 0.35, 2)  # 35% typical net contribution margin

        # 7-day immediate pilot capture
        projected_7_day_recovery = round(monthly_leak_revenue / 4.33, 2)
        projected_annual_recovered = round(annual_leak_revenue * 0.92, 2)  # 92% answer & dispatch efficiency

        # Competitor Capture Index (0-100) based on fleet scale and ticket exposure
        scale_factor = req.truck_count * 2.5
        ticket_factor = req.average_ticket / 250.0
        capture_idx = round(min(98.5, max(38.0, 48.0 + scale_factor + ticket_factor)), 1)

        benchmark_notes = (
            f"In the {req.zip_code} regional market, contractors in {req.trade} lose an average of "
            f"28% of all inbound prospects to unanswered rings. 65% of those callers do not leave a voicemail; "
            f"they immediately award the emergency repair to a competitor with a live answer."
        )

        recovery_plan: List[str] = [
            f"Step 1: Deploy DispatchEngine sub-1.2s AI voice answering on existing business line ({req.trade}).",
            "Step 2: Activate autonomous 2-way SMS qualification to instantly capture mobile callers during peak truck drive time.",
            f"Step 3: Route qualified emergency calls directly to on-call technician phone tree across all {req.truck_count} trucks.",
            f"Step 4: Recover an estimated ${projected_7_day_recovery:,.2f} in captured emergency revenue during the 7-day pilot.",
            f"Step 5: Protect an annual bottom-line profit of ${annual_lost_profit:,.2f} previously leaking to competing contractors.",
        ]

        return AuditReportResponse(
            trade=req.trade,
            truck_count=req.truck_count,
            monthly_call_volume=req.monthly_call_volume,
            average_ticket=req.average_ticket,
            zip_code=req.zip_code,
            missed_call_rate_pct=28.0,
            missed_call_count=missed_call_count,
            competitor_capture_rate_pct=65.0,
            lost_jobs_count=lost_jobs_count,
            monthly_leak_revenue=monthly_leak_revenue,
            annual_lost_profit=annual_lost_profit,
            competitor_capture_index=capture_idx,
            projected_7_day_recovery=projected_7_day_recovery,
            projected_annual_recovered_revenue=projected_annual_recovered,
            regional_benchmark_notes=benchmark_notes,
            recovery_plan=recovery_plan,
        )


audit_service = AuditService()
