from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.schemas.crew import (
    CrewAssignment,
    CrewVoucherData,
)


class CrewSettlementService:
    """
    Manages subcontractor crew dispatches, 1099 labor settlement vouchers,
    and real-time contractor net profit margins.
    """

    async def assign_crew_to_job(
        self,
        action_id: uuid.UUID,
        crew_payload: Dict[str, Any],
        db: AsyncSession,
    ) -> CrewVoucherData:
        """
        Assigns a trade subcontractor crew to a dispatch job, computes their
        percentage/piece-rate/flat labor payout, and generates a formal 1099 voucher.
        """
        stmt = (
            select(LeadAction)
            .options(selectinload(LeadAction.tenant))
            .where(LeadAction.id == action_id)
        )
        lead_action = (await db.execute(stmt)).scalar_one_or_none()
        if not lead_action:
            raise ValueError(f"Dispatch lead '{action_id}' not found")

        tenant = lead_action.tenant

        # 1. Resolve contract revenue
        contract_revenue = 1850.0
        if lead_action.invoice_data and lead_action.invoice_data.get("contract_total"):
            contract_revenue = float(lead_action.invoice_data["contract_total"])
        elif lead_action.proposal_data and lead_action.proposal_data.get("selected_tier"):
            contract_revenue = float(lead_action.proposal_data["selected_tier"].get("price", 1850.0))
        elif lead_action.signed_contract and lead_action.signed_contract.get("contract_total"):
            contract_revenue = float(lead_action.signed_contract["contract_total"])

        # 2. Resolve wholesale material costs
        material_costs = 380.0
        if lead_action.material_po and lead_action.material_po.get("total_material_cost") is not None:
            material_costs = float(lead_action.material_po["total_material_cost"])
        elif lead_action.profitability_data and lead_action.profitability_data.get("material_costs") is not None:
            material_costs = float(lead_action.profitability_data["material_costs"])

        # 3. Calculate crew labor payout
        payout_type = (crew_payload.get("payout_type") or "PERCENTAGE").upper()
        rate_amount = float(crew_payload.get("rate_amount") or 25.0)

        if payout_type == "PERCENTAGE":
            total_crew_payout = round(contract_revenue * (rate_amount / 100.0), 2)
        elif payout_type == "PIECE_RATE":
            unit_quantity = float(crew_payload.get("unit_quantity") or 18.0)
            total_crew_payout = round(rate_amount * unit_quantity, 2)
        else:  # FLAT
            total_crew_payout = round(rate_amount, 2)

        # 4. Compute true net contractor profit
        net_contractor_profit = round(contract_revenue - material_costs - total_crew_payout, 2)
        margin_pct = (
            round((net_contractor_profit / contract_revenue) * 100.0, 1)
            if contract_revenue > 0
            else 0.0
        )

        # 5. Build CrewAssignment
        trade_spec = (
            crew_payload.get("trade_specialty")
            or lead_action.action_type
            or "General Contracting"
        )
        assignment = CrewAssignment(
            crew_name=crew_payload.get("crew_name") or "Apex Primary Trade Crew",
            foreman_name=crew_payload.get("foreman_name") or "Carlos Mendez",
            foreman_phone=crew_payload.get("foreman_phone") or "+12025550188",
            trade_specialty=trade_spec,
            payout_type=payout_type,
            rate_amount=rate_amount,
            total_crew_payout=total_crew_payout,
        )

        # 6. Build Scope Summary & Voucher
        customer_name = (
            lead_action.metadata_payload.get("customer_name")
            or lead_action.metadata_payload.get("name")
            or "Property Owner"
        )
        address = (
            lead_action.metadata_payload.get("address")
            or lead_action.metadata_payload.get("job_address")
            or "Job Location"
        )
        scope = (
            crew_payload.get("scope_summary")
            or lead_action.qualification_summary
            or "Complete emergency restoration and installation per contract specifications."
        )

        voucher_num = f"VOUCH-2026-{uuid.uuid4().hex[:4].upper()}"

        voucher = CrewVoucherData(
            voucher_number=voucher_num,
            action_id=str(lead_action.id),
            customer_name=customer_name,
            job_address=address,
            scope_summary=scope,
            crew_assignment=assignment,
            contract_revenue=contract_revenue,
            material_cost=material_costs,
            net_contractor_profit=net_contractor_profit,
            margin_percentage=margin_pct,
            status="ASSIGNED",
            notes=crew_payload.get("notes") or "Standard 1099 settlement upon customer walkthrough sign-off.",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # 7. Update LeadAction
        lead_action.crew_data = voucher.model_dump()

        tier_label = "EXCELLENT" if margin_pct >= 50.0 else ("HEALTHY" if margin_pct >= 30.0 else "LOW")
        lead_action.profitability_data = {
            "contract_revenue": contract_revenue,
            "material_costs": material_costs,
            "estimated_labor_cost": total_crew_payout,
            "net_profit": net_contractor_profit,
            "margin_percentage": margin_pct,
            "margin_tier": tier_label,
        }

        await db.commit()
        await db.refresh(lead_action)
        logger.info(f"Subcontractor crew voucher {voucher_num} generated for action {lead_action.id}")
        return voucher


crew_settlement_service = CrewSettlementService()
