from typing import List, Optional
from pydantic import BaseModel, Field


class LockerDistributorBranch(BaseModel):
    """Regional wholesale distributor branch with 24/7 automated locker hardware."""
    branch_id: str = Field(..., description="Unique slug identifier (e.g. 'ferguson-alexandria')")
    distributor_name: str = Field(..., description="Wholesale distributor entity")
    branch_name: str = Field(..., description="Full human-readable branch facility name")
    address: str = Field(..., description="Street address")
    city: str = Field(..., description="City")
    state: str = Field(..., description="State code ('DC', 'VA', 'MD')")
    zip_code: str = Field(..., description="Postal code")
    lat: float = Field(..., description="Geographical latitude")
    lng: float = Field(..., description="Geographical longitude")
    emergency_gate_code: str = Field(..., description="Keypad pin code for perimeter access gate")
    after_hours_contact_phone: str = Field(..., description="24/7 on-call parts manager direct phone")
    active_lockers_available: int = Field(default=8, description="Number of currently vacant electronic lockers")


class LockerReservationItem(BaseModel):
    """Itemized wholesale inventory component reserved in after-hours locker."""
    part_sku: str = Field(..., description="Distributor catalog SKU or manufacturer part number")
    description: str = Field(..., description="Part description (e.g. 'Dual Run Capacitor 45/5 MFD 440V')")
    quantity: int = Field(default=1, description="Quantity reserved")
    unit_price: float = Field(..., description="Contractor wholesale price in USD")
    total_price: float = Field(..., description="Extended total price (quantity * unit_price)")


class LockerReservationVoucher(BaseModel):
    """Verified digital access voucher and PIN token for 24/7 parts locker pickup."""
    reservation_id: str = Field(..., description="Unique reservation voucher reference (e.g. 'LCK-2026-9812')")
    action_id: str = Field(..., description="Associated dispatch lead action UUID")
    distributor: LockerDistributorBranch = Field(..., description="Fulfilling distributor branch location")
    locker_box_number: str = Field(..., description="Assigned electronic bay identifier (e.g. 'Box #07')")
    secure_pickup_pin: str = Field(..., description="4-digit electronic keycode for locker terminal")
    items: List[LockerReservationItem] = Field(default_factory=list, description="Itemized reserved parts")
    material_subtotal: float = Field(..., description="Sum of parts wholesale pricing in USD")
    emergency_locker_fee: float = Field(default=35.00, description="After-hours staging and automation surcharge")
    total_cost: float = Field(..., description="Total charged to contractor supply account")
    access_instructions: str = Field(..., description="Step-by-step gate and locker terminal pickup protocol")
    navigation_url: str = Field(..., description="Google Maps turn-by-turn routing link")
    expires_at: str = Field(..., description="ISO 8601 expiration timestamp (4 hours from booking)")
    status: str = Field(default="CONFIRMED", description="Voucher status: 'CONFIRMED', 'PICKED_UP', 'EXPIRED'")
    technician_name: Optional[str] = Field(default=None, description="Dispatched service technician name")
    technician_phone: Optional[str] = Field(default=None, description="Technician SMS target phone")
    customer_address: Optional[str] = Field(default=None, description="Jobsite loss address")
    created_at: Optional[str] = Field(default=None, description="Reservation timestamp")


class LockerReserveRequest(BaseModel):
    """Payload to trigger autonomous 24/7 locker parts reservation."""
    preferred_region: Optional[str] = Field(default=None, description="Preferred DMV jurisdiction ('DC', 'VA', 'MD')")
    technician_name: Optional[str] = Field(default=None, description="Assigned field service tech")
    technician_phone: Optional[str] = Field(default=None, description="Target mobile number for automated SMS link")
    manual_items: Optional[List[LockerReservationItem]] = Field(default=None, description="Optional custom part items")
    branch_id: Optional[str] = Field(default=None, description="Optional direct branch override")


class LockerBranchQueryRequest(BaseModel):
    """Query payload to locate nearest stocking after-hours supply house lockers."""
    zip_code: Optional[str] = Field(default=None, description="Target 5-digit zip code")
    lat: Optional[float] = Field(default=None, description="GPS latitude")
    lng: Optional[float] = Field(default=None, description="GPS longitude")
    customer_address: Optional[str] = Field(default=None, description="Jobsite address string")
    trade: Optional[str] = Field(default="hvac", description="Trade category: 'hvac', 'plumbing', 'roofing', 'electrical'")
