from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DiagnosticTroubleshootRequest(BaseModel):
    """Field technician query for diagnostic troubleshooting assistance."""
    equipment_brand: str = Field(..., description="Brand or manufacturer (e.g. 'Carrier', 'Trane', 'Lennox', 'Navien', 'Square D')")
    equipment_type: str = Field(..., description="Trade equipment type (e.g. 'Heat Pump', 'Gas Furnace', 'Tankless Water Heater', 'Panel / Breaker')")
    fault_code_or_symptom: str = Field(..., description="Flashing LED count, diagnostic fault code, or observed physical symptom (e.g. 'Code 31', '3 Flashes', 'No heat, flame drops after 4 seconds')")
    technician_notes: Optional[str] = Field(None, description="Optional spoken dictation or observed multimeter measurements")


class DiagnosticTroubleshootGuide(BaseModel):
    """Structured AI field diagnostic guide with step-by-step procedures and multimeter test targets."""
    equipment_context: str = Field(..., description="Summary of the brand, system architecture, and reported error code")
    probable_root_causes: List[str] = Field(default_factory=list, description="Ranked list of most likely root causes")
    step_by_step_test_procedure: List[str] = Field(default_factory=list, description="Ordered diagnostic isolation test sequence")
    multimeter_readings_expected: Dict[str, str] = Field(default_factory=dict, description="Expected electrical and sensor readings (volts, microamps, ohms, MFD)")
    common_replacement_parts: List[str] = Field(default_factory=list, description="Common failure components with OEM specifications")
    safety_warnings: List[str] = Field(default_factory=list, description="Critical OSHA, high voltage, and refrigerant/gas hazard alerts")
