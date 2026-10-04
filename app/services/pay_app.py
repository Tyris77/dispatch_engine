import math
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.pay_app import AIAContractProgressPayment, ScheduleOfValuesItem

SOV_TEMPLATE_PHASES = [
    ("01-100", "Mobilization, Safety Setup & Temporary Facilities", 0.08),
    ("02-410", "Selective Demolition, Hazardous Abatement & Disposal", 0.12),
    ("15-050", "Mechanical / Core Equipment & Rough-In Infrastructure", 0.35),
    ("16-100", "High-Voltage Distribution & Automated Controls Wiring", 0.20),
    ("07-200", "Thermal Insulation, Vapor Barrier & Weather Enclosure", 0.15),
    ("23-080", "System Start-Up, TAB Testing & Architect Closeout", 0.10),
]


class PayAppService:
    """Commercial AIA Document G702 and G703 progress payment application engine."""

    @staticmethod
    def _resolve_contract_sum(lead: LeadAction) -> float:
        """Derive the commercial contract sum from contract, diagnostic, or metadata."""
        contract = lead.signed_contract or {}
        if contract.get("tier_price"):
            try:
                return float(contract["tier_price"])
            except (ValueError, TypeError):
                pass

        diag = lead.diagnostic_data or {}
        if diag.get("estimated_cost"):
            try:
                return float(diag["estimated_cost"])
            except (ValueError, TypeError):
                pass

        meta = lead.metadata_payload or {}
        for key in ("contract_sum", "commercial_value", "job_value", "estimated_cost"):
            if meta.get(key):
                try:
                    return float(meta[key])
                except (ValueError, TypeError):
                    pass

        return 78500.00

    @staticmethod
    def _project_name(lead: LeadAction) -> str:
        diag = lead.diagnostic_data or {}
        meta = lead.metadata_payload or {}
        addr = lead.extracted_address or meta.get("address") or "Commercial Jobsite"
        category = lead.category or "Commercial Mechanical / Architectural Upgrade"
        return f"{category} - {addr}"

    def generate_aia_payment_application(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        progress_pct: float = 65.0,
        retainage_pct: float = 10.0,
        application_number: int = 1,
        architect_name: str = "Studio Architecture & Engineering P.C.",
    ) -> AIAContractProgressPayment:
        """
        Builds a formal AIA Document G702 & G703 Application and Certificate for Payment.
        Calculates line-by-line Schedule of Values (SOV), 10% retainage escrow withholding,
        previous certificates deduction, and net current payment due.
        """
        contract_sum = round(self._resolve_contract_sum(lead_action), 2)
        target_progress = max(0.0, min(100.0, progress_pct))
        retainage_rate = max(0.0, min(50.0, retainage_pct))

        line_items: List[ScheduleOfValuesItem] = []
        total_sched = 0.0
        total_completed_stored_accum = 0.0
        total_retainage_accum = 0.0
        total_prev_completed_accum = 0.0

        num_phases = len(SOV_TEMPLATE_PHASES)
        for idx, (code, desc, share) in enumerate(SOV_TEMPLATE_PHASES):
            # Allocate scheduled value proportionally
            if idx == num_phases - 1:
                item_sched = round(contract_sum - total_sched, 2)
            else:
                item_sched = round(contract_sum * share, 2)
                total_sched += item_sched

            # Phase progression logic: earlier phases complete first
            phase_threshold = (idx + 1) * (100.0 / num_phases)
            if target_progress >= phase_threshold:
                item_pct = 100.0
            elif target_progress <= (idx * (100.0 / num_phases)):
                item_pct = 0.0
            else:
                sub_span = 100.0 / num_phases
                item_pct = round(((target_progress - (idx * sub_span)) / sub_span) * 100.0, 1)

            total_item_comp = round(item_sched * (item_pct / 100.0), 2)

            # Split between previous applications and this period
            if application_number > 1:
                prev_pct = max(0.0, item_pct * 0.5)
                prev_work = round(item_sched * (prev_pct / 100.0), 2)
                this_work = round(total_item_comp - prev_work, 2)
            else:
                prev_work = 0.0
                this_work = total_item_comp

            # Stored materials on site (e.g. 5% of this work for uninstalled assemblies)
            stored_mat = round(this_work * 0.05, 2) if this_work > 0 and item_pct < 100.0 else 0.0
            actual_comp_and_stored = round(min(item_sched, total_item_comp + stored_mat), 2)

            effective_pct = round((actual_comp_and_stored / (item_sched or 1.0)) * 100.0, 1)
            balance = round(item_sched - actual_comp_and_stored, 2)
            ret_amt = round(actual_comp_and_stored * (retainage_rate / 100.0), 2)

            total_completed_stored_accum += actual_comp_and_stored
            total_retainage_accum += ret_amt
            total_prev_completed_accum += prev_work

            line_items.append(
                ScheduleOfValuesItem(
                    item_number=code,
                    description=desc,
                    scheduled_value=item_sched,
                    work_completed_previous=prev_work,
                    work_completed_this_period=this_work,
                    materials_stored=stored_mat,
                    total_completed_stored=actual_comp_and_stored,
                    percent_complete=effective_pct,
                    balance_to_finish=balance,
                    retainage_rate_pct=retainage_rate,
                    retainage_amount=ret_amt,
                )
            )

        # Standard AIA G702 Summary Calculations:
        # Line 1: Original Contract Sum
        orig_sum = contract_sum
        # Line 2: Net change by Change Orders
        net_changes = 0.0
        # Line 3: Contract Sum to Date (1 + 2)
        sum_to_date = round(orig_sum + net_changes, 2)
        # Line 4: Total Completed and Stored to Date
        tot_comp_stored = round(total_completed_stored_accum, 2)
        # Line 5: Total Retainage
        tot_retainage = round(total_retainage_accum, 2)
        # Line 6: Total Earned Less Retainage
        earned_less_ret = round(tot_comp_stored - tot_retainage, 2)
        # Line 7: Less Previous Certificates for Payment
        less_prev = round(total_prev_completed_accum * (1.0 - (retainage_rate / 100.0)), 2)
        # Line 8: Current Payment Due (Line 6 - Line 7)
        curr_due = round(max(0.0, earned_less_ret - less_prev), 2)
        # Line 9: Balance to Finish, Plus Retainage (Line 3 - Line 6)
        bal_to_finish_plus_ret = round(sum_to_date - earned_less_ret, 2)

        period_to_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

        pay_app = AIAContractProgressPayment(
            application_number=application_number,
            period_to=period_to_str,
            project_name=self._project_name(lead_action),
            contractor_name=tenant.name,
            architect_name=architect_name,
            original_contract_sum=orig_sum,
            net_change_orders=net_changes,
            contract_sum_to_date=sum_to_date,
            total_completed_stored=tot_comp_stored,
            total_retainage=tot_retainage,
            less_previous_certificates=less_prev,
            current_payment_due=curr_due,
            balance_to_finish_plus_retainage=bal_to_finish_plus_ret,
            line_items=line_items,
        )

        return pay_app

    async def get_or_create_pay_app(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        db: AsyncSession,
        progress_pct: Optional[float] = None,
        retainage_pct: Optional[float] = None,
    ) -> AIAContractProgressPayment:
        """Retrieve existing stored pay application or generate a new one."""
        if lead_action.pay_app_data and progress_pct is None and retainage_pct is None:
            try:
                return AIAContractProgressPayment.model_validate(lead_action.pay_app_data)
            except Exception as exc:
                logger.warning(f"Invalid pay_app_data for lead {lead_action.id}: {exc}")

        prog = progress_pct if progress_pct is not None else 65.0
        ret = retainage_pct if retainage_pct is not None else 10.0

        pay_app = self.generate_aia_payment_application(
            lead_action=lead_action,
            tenant=tenant,
            progress_pct=prog,
            retainage_pct=ret,
        )

        lead_action.pay_app_data = pay_app.model_dump()
        await db.commit()
        return pay_app


pay_app_service = PayAppService()
