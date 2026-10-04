from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class UtilityRebateProgram(BaseModel):
    """Specific utility rebate or federal tax credit program and qualification threshold."""
    program_name: str = Field(..., description="Official program title (e.g. 'Pepco Home Energy Savings', 'Federal IRA 25C')")
    utility_provider: str = Field(..., description="Issuing utility company or government agency")
    eligible_trade: str = Field(..., description="Eligible trade category (HVAC, Plumbing, Electrical, Roofing)")
    rebate_amount: float = Field(..., description="Cash rebate or tax credit amount in dollars")
    efficiency_criteria: str = Field(..., description="Minimum energy efficiency standard required to qualify")


class RebateCalculationResult(BaseModel):
    """Aggregate rebate breakdown calculation for proposal tiers or customer quotes."""
    gross_price: float = Field(..., description="Gross proposal contract price before incentives")
    total_rebates_available: float = Field(..., description="Sum of all applicable utility rebates and tax credits")
    net_customer_investment: float = Field(..., description="Net out-of-pocket customer cost after rebates")
    qualifying_programs: List[UtilityRebateProgram] = Field(default_factory=list, description="Itemized qualifying rebate programs")


class RebateClaimDossier(BaseModel):
    """Pre-filled official utility rebate claim dossier ready for printable customer & contractor filing."""
    claim_id: str = Field(..., description="Unique rebate claim reference token")
    action_id: str = Field(..., description="ID of the underlying LeadAction")
    tenant_slug: str = Field(..., description="Contractor tenant slug")
    tenant_name: str = Field(..., description="Contractor legal business name")
    contractor_license: str = Field(..., description="Contractor state master mechanical/plumbing license number")
    contractor_phone: str = Field(..., description="Contractor business phone")
    contractor_address: str = Field(..., description="Contractor business headquarters address")
    customer_name: str = Field(..., description="Property owner / claimant name")
    customer_phone: str = Field(..., description="Claimant primary phone number")
    service_address: str = Field(..., description="Physical installation address")
    utility_provider: str = Field(..., description="Electric or gas utility serving the property")
    installed_equipment_type: str = Field(..., description="Category of equipment installed")
    installed_equipment_brand: str = Field(..., description="Manufacturer brand name")
    installed_equipment_model: str = Field(..., description="AHRI verified model number")
    installed_equipment_serial: str = Field(..., description="Installed unit serial number")
    ahri_certificate_number: str = Field(..., description="AHRI Certified Reference Number")
    installation_date: str = Field(..., description="Date equipment was commissioned")
    programs: List[UtilityRebateProgram] = Field(default_factory=list, description="List of qualified incentive programs")
    total_rebate_amount: float = Field(..., description="Total combined rebate and credit dollars")
    status: str = Field(default="PRE_FILLED", description="Current filing state of the claim")
