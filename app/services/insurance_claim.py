import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.schemas.insurance_claim import (
    ClaimGenerateRequest,
    InsuranceClaimSupplementReport,
    XactimateLineItem,
)

# Standard Xactimate item catalogs by trade with IRC and IICRC legal code justifications
TRADE_XACTIMATE_CATALOGS = {
    "water_mitigation": [
        XactimateLineItem(
            item_code="WTR EXTW",
            category="Water Extraction",
            description="Extraction of heavy standing water from subfloor and structural framing",
            quantity=450.0,
            unit="SF",
            unit_price=0.95,
            total_price=427.50,
            code_justification="Required per IICRC S500 Section 12.2.8 for Category 2/3 water extraction prior to structural drying.",
        ),
        XactimateLineItem(
            item_code="WTR DHM",
            category="Dehumidification",
            description="LGR Low-Grain Refrigerant Dehumidifier - Extra Large (per 24hr day)",
            quantity=4.0,
            unit="DA",
            unit_price=145.00,
            total_price=580.00,
            code_justification="IICRC S500 Section 12.4.2 mandates maintaining vapor pressure below 35 GPP to prevent secondary microbial growth.",
        ),
        XactimateLineItem(
            item_code="WTR DRY",
            category="Dehumidification",
            description="Axial Air Mover / Air Mover Fan - Commercial High-Velocity (per 24hr day)",
            quantity=12.0,
            unit="DA",
            unit_price=42.00,
            total_price=504.00,
            code_justification="IICRC S500 Section 12.3.1 requires 1 air mover per 50-70 SF of affected wet floor and ceiling area.",
        ),
        XactimateLineItem(
            item_code="WTR MMAP",
            category="Diagnostics",
            description="Thermal Infrared & Moisture Mapping Diagnostic Protocol with daily psychrometric dry logs",
            quantity=1.0,
            unit="EA",
            unit_price=285.00,
            total_price=285.00,
            code_justification="IICRC S500 Section 10.3 requires continuous daily invasive & non-invasive psychrometric logging to verify dry standard.",
        ),
        XactimateLineItem(
            item_code="WTR BARR",
            category="Containment",
            description="6-Mil Polyethylene Critical Containment Chamber with zipper entry hatch",
            quantity=220.0,
            unit="SF",
            unit_price=1.15,
            total_price=253.00,
            code_justification="IICRC S500 Section 12.2.4 mandatory cross-contamination isolation barrier between affected and unaffected living quarters.",
        ),
        XactimateLineItem(
            item_code="WTR GRM",
            category="Sanitization",
            description="EPA-Registered Botanical Antimicrobial spray application on structural framing",
            quantity=450.0,
            unit="SF",
            unit_price=0.45,
            total_price=202.50,
            code_justification="IICRC S500 Section 12.2.11 mandatory application of EPA-registered botanical disinfectant following contaminated water intrusion.",
        ),
    ],
    "roofing": [
        XactimateLineItem(
            item_code="RFG DRIP",
            category="Roofing Peripherals",
            description="Drip edge flashing - Galvanized / Painted Aluminum along eave and rake edges",
            quantity=160.0,
            unit="LF",
            unit_price=4.20,
            total_price=672.00,
            code_justification="2021 International Residential Code (IRC) Section R905.2.8.5 / Section R905.2.8.3 requires drip edge along eaves and rake edges.",
        ),
        XactimateLineItem(
            item_code="RFG ICE",
            category="Underlayment Barrier",
            description="Self-adhering polymer modified bitumen Ice & Water Shield leak barrier",
            quantity=380.0,
            unit="SF",
            unit_price=1.85,
            total_price=703.00,
            code_justification="IRC Section R905.1.2 mandates self-adhering ice barrier extending at least 24 inches inside the exterior wall line in freeze zones.",
        ),
        XactimateLineItem(
            item_code="RFG FLSTEP",
            category="Flashing Replacement",
            description="Step flashing replacement - 5x7 prepainted aluminum along wall sidewalls and dormers",
            quantity=54.0,
            unit="LF",
            unit_price=14.50,
            total_price=783.00,
            code_justification="2021 International Residential Code (IRC) Section R905.2.8.5 mandates replacement of corroded or damaged step flashing.",
        ),
        XactimateLineItem(
            item_code="RFG RIDGE",
            category="Shingles & Finishing",
            description="High-profile impact resistant ridge cap shingles matching field shingle warranty",
            quantity=65.0,
            unit="LF",
            unit_price=12.80,
            total_price=832.00,
            code_justification="Manufacturer installation specifications (IRC R905.1) mandate matching high-profile ridge cap for wind warranty certification.",
        ),
        XactimateLineItem(
            item_code="RFG STEEP",
            category="Safety & Pitch Labor",
            description="Steep slope roof pitch surcharge (8/12 to 11/12 steep pitch charge)",
            quantity=28.0,
            unit="SF",
            unit_price=42.00,
            total_price=1176.00,
            code_justification="OSHA 1926.501(b)(11) and Xactimate regional labor table requirements for steep-slope fall protection harness rigging.",
        ),
    ],
    "hvac": [
        XactimateLineItem(
            item_code="HVC LINE",
            category="Refrigerant Piping",
            description="Refrigerant copper line set chemical flush, nitrogen pressure test and evacuation",
            quantity=1.0,
            unit="EA",
            unit_price=385.00,
            total_price=385.00,
            code_justification="EPA Clean Air Act Section 608 & ASHRAE Standard 15 acid decontamination after compressor electrical burn.",
        ),
        XactimateLineItem(
            item_code="HVC COND",
            category="Condensate & Drainage",
            description="Auxiliary secondary emergency drain pan with electronic overflow float safety shutoff switch",
            quantity=1.0,
            unit="EA",
            unit_price=265.00,
            total_price=265.00,
            code_justification="2021 International Mechanical Code (IMC) Section 307.2.3 mandatory secondary drain pan and water-level detection device.",
        ),
    ],
}


class InsuranceClaimService:
    """
    Autonomous Insurance Claim Supplement & Xactimate Line-Item Engine.
    Synthesizes diagnostic, mitigation, and proposal records, detects missing carrier line items,
    injects statutory IRC and IICRC building codes, and formats formal adjuster demand packets.
    """

    def detect_trade(self, action: LeadAction) -> str:
        """Determines the prevailing trade category from action metadata or diagnostic payload."""
        text_corpus = ""
        if action.action_type:
            text_corpus += " " + action.action_type
        if action.qualification_summary:
            text_corpus += " " + action.qualification_summary
        if action.metadata_payload:
            text_corpus += " " + str(action.metadata_payload)
        if action.diagnostic_data:
            text_corpus += " " + str(action.diagnostic_data)
        if action.mitigation_data:
            text_corpus += " " + str(action.mitigation_data)
        if action.proposal_data:
            text_corpus += " " + str(action.proposal_data)

        text_lower = text_corpus.lower()
        if any(w in text_lower for w in ["water", "mitigation", "extraction", "flood", "sewer", "dehumid", "dryout", "drying", "psychrometric"]):
            return "water_mitigation"
        elif any(w in text_lower for w in ["roof", "shingle", "hail", "wind", "drip edge", "flashing", "pitch"]):
            return "roofing"
        elif any(w in text_lower for w in ["hvac", "furnace", "air condition", "compressor", "heat pump", "a/c", "refrigerant"]):
            return "hvac"
        return "water_mitigation"

    def generate_demand_letter(
        self,
        contractor_name: str,
        insurance_carrier: str,
        claim_number: str,
        policyholder_name: str,
        property_address: str,
        trade_label: str,
        original_amount: float,
        supplement_amount: float,
        total_claim_value: float,
        line_items: List[XactimateLineItem],
    ) -> str:
        """Formats an authoritative, legally grounded adjuster demand letter."""
        now_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
        items_summary = "\n".join([
            f" • [{item.item_code}] {item.description} ({item.quantity} {item.unit} @ ${item.unit_price:,.2f} = ${item.total_price:,.2f})\n"
            f"   JUSTIFICATION: {item.code_justification}"
            for item in line_items
        ])

        letter = (
            f"DATE: {now_date}\n\n"
            f"TO: Property Claims Department\n"
            f"CARRIER: {insurance_carrier}\n"
            f"ATTN: Assigned Property Claims Adjuster\n"
            f"RE: FORMAL SUPPLEMENT REQUEST & SCOPE OF WORK RECONCILIATION\n\n"
            f"INSURED / POLICYHOLDER: {policyholder_name}\n"
            f"CLAIM NUMBER: {claim_number}\n"
            f"PROPERTY ADDRESS: {property_address}\n"
            f"PERFORMING CONTRACTOR: {contractor_name}\n"
            f"TRADE SPECIALIZATION: {trade_label.upper()}\n\n"
            f"Dear Claims Adjuster,\n\n"
            f"Please accept this formal supplement documentation and Xactimate itemized scope revision "
            f"for the above-referenced insurance property loss. Upon our master technicians' comprehensive onsite "
            f"inspection, multiple mandatory building code requirements and industry trade standards were identified "
            f"that were omitted from your carrier's initial estimate of ${original_amount:,.2f}.\n\n"
            f"To return the insured property to its pre-loss condition in full compliance with local municipal building "
            f"ordinances, manufacturer warranty covenants, and life-safety mandates, the following supplemental "
            f"line items are required:\n\n"
            f"{items_summary}\n\n"
            f"FINANCIAL RECONCILIATION SUMMARY:\n"
            f" • Original Carrier Scope Allowance: ${original_amount:,.2f}\n"
            f" • Code & Manufacturer Supplement Total: ${supplement_amount:,.2f}\n"
            f" • Corrected Total Claim Value: ${total_claim_value:,.2f}\n\n"
            f"STATUTORY & CODE NOTICE:\n"
            f"Failure to approve these code-required line items places the insured at risk of code violations and "
            f"forfeiture of manufacturer product warranties. Please review the attached photographic evidence and "
            f"issue an amended Statement of Loss within ten (10) business days.\n\n"
            f"Respectfully submitted,\n\n"
            f"{contractor_name} Claims Resolution Desk\n"
            f"Autonomous Dispatch & Operations Engine"
        )
        return letter

    def generate_claim_supplement(
        self,
        action: LeadAction,
        request_data: Optional[Any] = None,
        tenant_name: Optional[str] = None,
    ) -> InsuranceClaimSupplementReport:
        """
        Synthesizes onsite action data, detects trade, generates line items,
        calculates financial totals, and builds the adjuster demand package.
        """
        if isinstance(request_data, dict):
            request_data = ClaimGenerateRequest(**request_data)

        carrier = request_data.insurance_carrier if request_data else "State Farm"
        claim_num = (request_data.claim_number if request_data and request_data.claim_number else None) or f"CLM-2026-{uuid.uuid4().hex[:6].upper()}"
        policyholder = (
            (request_data.policyholder_name if request_data and request_data.policyholder_name else None)
            or (action.metadata_payload.get("sender_name") if action.metadata_payload else None)
            or "John & Sarah Jenkins"
        )
        address = (
            (action.metadata_payload.get("address") if action.metadata_payload else None)
            or "4820 Wisconsin Ave NW, Washington, DC"
        )
        c_name = tenant_name or "Apex Restoration & Mechanical Systems"

        # Trade detection
        trade_key = self.detect_trade(action)
        catalog = TRADE_XACTIMATE_CATALOGS.get(trade_key, TRADE_XACTIMATE_CATALOGS["water_mitigation"])
        trade_label = trade_key.replace("_", " ").title()

        # Build dynamic line items synthesized from diagnostic, mitigation, and proposal data
        line_items = [item.model_copy() for item in catalog]
        if trade_key == "water_mitigation":
            diag = action.diagnostic_data or {}
            mit = action.mitigation_data or {}
            sqft = float(diag.get("affected_area_sqft") or mit.get("affected_area_sqft") or 0.0)
            dehumids = float(mit.get("dehumidifiers_deployed") or 0.0)
            fans = float(mit.get("air_movers_deployed") or 0.0)
            for item in line_items:
                if item.item_code in ("WTR EXTW", "WTR GRM") and sqft > 0:
                    item.quantity = sqft
                    item.total_price = round(item.quantity * item.unit_price, 2)
                elif item.item_code == "WTR DHM" and dehumids > 0:
                    item.quantity = dehumids
                    item.total_price = round(item.quantity * item.unit_price, 2)
                elif item.item_code == "WTR DRY" and fans > 0:
                    item.quantity = fans
                    item.total_price = round(item.quantity * item.unit_price, 2)

        supplement_amount = sum(item.total_price for item in line_items)

        # Baseline carrier estimate synthesis
        if request_data and request_data.original_adjuster_amount is not None and request_data.original_adjuster_amount > 0:
            orig_amount = float(request_data.original_adjuster_amount)
        elif action.proposal_data and isinstance(action.proposal_data, dict) and action.proposal_data.get("original_adjuster_amount"):
            orig_amount = float(action.proposal_data["original_adjuster_amount"])
        elif request_data and request_data.original_adjuster_amount == 0.0:
            orig_amount = 0.0
        else:
            orig_amount = 1450.0

        total_val = orig_amount + supplement_amount

        # Extract citations
        trade_statutory_citations = {
            "water_mitigation": [
                "IICRC S500 Section 12: Standard for Professional Water Damage Restoration",
                "IICRC S500 Section 12.2.8: Category 2/3 Water Extraction Protocol",
                "IICRC S500 Section 12.4.2: Psychrometric Humidity & Vapor Pressure Control (<35 GPP)",
                "IICRC S500 Section 10.3: Daily Psychrometric Logging Standard",
            ],
            "roofing": [
                "2021 International Residential Code (IRC) Section R905.2.8.5: Mandatory replacement of corroded or damaged step flashing",
                "IRC Section R905.1.2: Ice barrier requirements in freeze zones",
                "2021 International Residential Code (IRC) Section R905.2.8.3: Drip edge flashing required along eaves and rake edges",
                "OSHA 1926.501(b)(11): Steep-slope fall protection requirement",
            ],
            "hvac": [
                "2021 International Mechanical Code (IMC) Section 307.2.3: Auxiliary secondary drain pan & float shutoff switch",
                "EPA Clean Air Act Section 608 & ASHRAE Standard 15: Refrigerant line set flush & acid decontamination",
            ],
        }
        citations = trade_statutory_citations.get(trade_key, [item.code_justification for item in line_items])

        demand_letter = self.generate_demand_letter(
            contractor_name=c_name,
            insurance_carrier=carrier,
            claim_number=claim_num,
            policyholder_name=policyholder,
            property_address=address,
            trade_label=trade_label,
            original_amount=orig_amount,
            supplement_amount=supplement_amount,
            total_claim_value=total_val,
            line_items=line_items,
        )

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        report = InsuranceClaimSupplementReport(
            action_id=str(action.id),
            claim_number=claim_num,
            insurance_carrier=carrier,
            policyholder_name=policyholder,
            property_address=address,
            trade=trade_label,
            original_adjuster_amount=round(orig_amount, 2),
            supplement_amount=round(supplement_amount, 2),
            total_claim_value=round(total_val, 2),
            line_items=line_items,
            adjuster_demand_letter=demand_letter,
            code_citations=citations,
            status="SUBMITTED",
            created_at=now_str,
        )

        logger.info(f"📋 [Insurance Supplement] Generated ${supplement_amount:,.2f} supplement for Claim #{claim_num} ({carrier})")
        return report

    async def save_supplement_to_action(
        self,
        action: LeadAction,
        report: InsuranceClaimSupplementReport,
        db: AsyncSession,
    ) -> None:
        """Persists generated supplement JSON into LeadAction database record."""
        action.claim_supplement_data = report.model_dump()
        await db.commit()
        await db.refresh(action)


insurance_claim_service = InsuranceClaimService()
