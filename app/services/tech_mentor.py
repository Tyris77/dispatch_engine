import json
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger
from app.schemas.tech_mentor import (
    DiagnosticTroubleshootGuide,
    DiagnosticTroubleshootRequest,
)

# Comprehensive field technician deterministic troubleshooting catalog
DETERMINISTIC_FAULT_CATALOG: List[Dict[str, Any]] = [
    {
        "keywords": ["carrier", "bryant", "payne", "31", "pressure switch", "high limit"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Carrier / Bryant Inducing Draft Gas Furnace (Code 31 - High Limit / Pressure Switch Open)",
            probable_root_causes=[
                "Restricted or blocked condensate P-trap / drain line causing water backup into inducer housing",
                "Obstruction or bird nest in PVC intake/exhaust vent termination",
                "Inducer draft motor failing or weak run capacitor (< 3.0 µF)",
                "Cracked or split vinyl pressure switch sensing tubing",
                "Cracked primary heat exchanger causing erratic draft pressure",
            ],
            step_by_step_test_procedure=[
                "Step 1: Disconnect power and verify condensate collector box and drain trap are completely drained and unblocked.",
                "Step 2: Inspect 2-inch or 3-inch PVC flue terminations outside the building for snow, ice, or debris blockages.",
                "Step 3: Connect digital dual-port manometer in series with pressure switch; turn on furnace and read draft (must exceed -0.65 in. W.C.).",
                "Step 4: Measure voltage across pressure switch terminals: 24VAC indicates switch is open (fault condition); 0VAC indicates closed (normal).",
                "Step 5: If draft exceeds -0.75 in. W.C. but switch remains open, replace defective pressure switch assembly.",
            ],
            multimeter_readings_expected={
                "Draft Manometer Target": ">= -0.65 in. W.C. at inducer port",
                "Voltage Across Closed Switch": "0.0 VAC (continuity closed)",
                "Voltage Across Open Switch": "24.0 VAC (open safety circuit)",
                "Inducer Motor Supply Voltage": "120.0 VAC ± 10%",
                "Inducer Motor Running Amps": "0.85A - 1.45A FLA",
            },
            common_replacement_parts=[
                "Carrier Dual Pressure Switch Assembly (HK06WC024 / HK06WC076)",
                "Fasco Draft Inducer Motor Kit (326625-761)",
                "Silicone Draft Tubing (1/8-inch ID)",
                "Condensate Trap Cleanout Plug & O-Ring",
            ],
            safety_warnings=[
                "DANGER: 120V shock hazard. Disconnect service disconnect before servicing wiring harness.",
                "Inspect heat exchanger for rollout or cracks if pressure switch trips intermittently during burner operation.",
            ],
        ),
    },
    {
        "keywords": ["carrier", "bryant", "33", "limit circuit", "overheat", "lockout"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Carrier / Bryant High Efficiency Furnace (Code 33 - Limit Circuit Lockout / Overheat)",
            probable_root_causes=[
                "Severe airflow restriction from dirty 1-inch or 4-inch pleated air filter",
                "Blower motor failed or weak capacitor causing heat exchanger overheat",
                "A-coil face blocked with pet dander, lint, or mildew",
                "High limit switch fatigued and opening below rated temperature (e.g. opens at 140°F instead of 180°F)",
                "Gas manifold pressure set too high (> 3.5 in. W.C. on natural gas)",
            ],
            step_by_step_test_procedure=[
                "Step 1: Check and replace customer air filter immediately.",
                "Step 2: Measure external static pressure across supply and return plenums with static probes (target <= 0.50 in. W.C.).",
                "Step 3: Verify blower motor rotates freely and ECM module / capacitor is operating at full CFM.",
                "Step 4: Check temperature rise across furnace (supply plenum temp minus return plenum temp); compare against data plate (typical 40°F - 70°F).",
                "Step 5: Test continuity of main primary high limit switch on back of burner vestibule.",
            ],
            multimeter_readings_expected={
                "External Static Pressure": "<= 0.55 in. W.C. total external static",
                "Temperature Rise": "45°F - 65°F (per unit data plate rating)",
                "Blower Motor Capacitor": "10.0 µF ± 6% (or ECM 120V/240V control signal)",
                "Limit Switch Drop": "0.0 VAC across terminals when cool",
            },
            common_replacement_parts=[
                "Primary High Limit Switch (L180-40F / HH12ZA180)",
                "Blower Run Capacitor (10 µF / 370-440 VAC)",
                "Genteq ECM 3.0 Blower Module",
            ],
            safety_warnings=[
                "Allow heat exchanger to cool for 15 minutes before touching primary limit sensor.",
                "Do NOT jumper high limit switch during operational heating test.",
            ],
        ),
    },
    {
        "keywords": ["carrier", "bryant", "13", "14", "ignition", "flame", "lockout", "no heat"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Carrier Gas Furnace (Code 13/14 - Ignition Lockout / Flame Rectification Loss)",
            probable_root_causes=[
                "Oxidized or carbon-fouled flame rectification sensor rod",
                "Defective silicon nitride hot surface igniter (open circuit or high resistance)",
                "Manual gas shutoff valve closed or gas supply pressure absent",
                "Faulty furnace chassis ground causing microamp rectification failure",
            ],
            step_by_step_test_procedure=[
                "Step 1: Observe sequence of operation: Inducer on -> Igniter glows -> Gas valve clicks open -> Flame ignites for 4 seconds then shuts off.",
                "Step 2: If flame shuts off after 4 seconds, remove flame sensor and clean rod with fine steel wool (do not use sandpaper).",
                "Step 3: Connect multimeter in series with flame sensor wire in DC Microamps (µA) mode; target reading must be between 1.5 µA and 4.5 µA DC.",
                "Step 4: If igniter does not glow, measure resistance across igniter spade pins (target 45 - 90 Ω cold; replace if infinite OL).",
                "Step 5: Verify continuous earth ground connection from breaker panel to furnace chassis (< 1.0 Ω).",
            ],
            multimeter_readings_expected={
                "Flame Sensor Rectification": "1.5 µA to 4.5 µA DC (steady signal)",
                "Hot Surface Igniter Resistance": "45 to 90 Ω cold (Silicon Nitride)",
                "Gas Valve Coil Voltage": "24.0 VAC during trial for ignition",
                "Chassis Earth Ground": "< 1.0 Ω to electrical service ground",
            },
            common_replacement_parts=[
                "Carrier Flame Sensor Rod (LH680014 / LH680005)",
                "Silicon Nitride Igniter 120V (LH33ZS004)",
                "White-Rodgers 24V Combination Gas Valve (EF32CW196)",
            ],
            safety_warnings=[
                "DANGER: Natural gas / LP gas explosive atmosphere hazard. Check for gas leaks with combustible gas detector.",
                "Hot surface igniter reaches 2,400°F within 10 seconds. Do not touch.",
            ],
        ),
    },
    {
        "keywords": ["trane", "american standard", "2 flashes", "3 flashes", "4 flashes", "pressure", "switch"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Trane / American Standard XR/XV Furnace (Flashing LED Safety Code)",
            probable_root_causes=[
                "2 Flashes: Pressure switch error - draft inducer not pulling sufficient vacuum or tubing split",
                "3 Flashes: Thermal limit switch open - excessive temperature rise from restricted filter",
                "4 Flashes: Flame sensed without gas valve energized - stuck open gas valve or shorted flame circuit",
            ],
            step_by_step_test_procedure=[
                "Step 1: Count red/amber diagnostic LED blink sequence on integrated furnace control board through sight glass.",
                "Step 2: If 2 Flashes, test pressure switch with manometer (target >= -0.70 in. W.C.). Inspect exhaust termination outside.",
                "Step 3: If 3 Flashes, check air filter, supply registers, and measure 24V circuit continuity across limit switch (SWT01614).",
                "Step 4: If 4 Flashes, de-energize immediately and inspect gas valve for mechanical sticking.",
            ],
            multimeter_readings_expected={
                "Pressure Switch Terminal Drop": "0.0 VAC when draft satisfied",
                "Limit Circuit Drop": "0.0 VAC closed / 24.0 VAC open",
                "Control Board Transformer Secondary": "24.0 - 27.5 VAC",
            },
            common_replacement_parts=[
                "Trane Integrated Furnace Control Board (CNT07541 / D341396P01)",
                "Pressure Switch Assembly (SWT03337)",
                "Trane Silicon Nitride Igniter (IGN00145)",
            ],
            safety_warnings=[
                "High voltage 120V present at control board door interlock switch.",
            ],
        ),
    },
    {
        "keywords": ["navien", "rinnai", "tankless", "e003", "e012", "e110", "water heater"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Navien NPE / Rinnai RU Series Condensing Tankless (Error E003 / E012 - Ignition Failure)",
            probable_root_causes=[
                "Dynamic gas inlet pressure dropping below 3.5 in. W.C. (Natural Gas) or 8.0 in. W.C. (Propane) during firing",
                "Gas meter undersized for 199k BTU peak demand",
                "Spark electrode assembly corroded or gap out of spec (spec 3.5mm)",
                "Condensate trap backed up inside secondary heat exchanger",
            ],
            step_by_step_test_procedure=[
                "Step 1: Hook up digital manometer to inlet gas test port on bottom of unit; monitor static pressure (7.0 in. W.C. NG).",
                "Step 2: Turn on 3 hot water faucets to demand 100% firing rate; verify dynamic gas pressure does NOT drop below 3.5 in. W.C.",
                "Step 3: Clean stainless steel spark electrode and flame rod with fine abrasive pad; set gap to 3.5mm.",
                "Step 4: Remove and flush internal condensate trap bottle with clean water to clear neutralizer sediment.",
            ],
            multimeter_readings_expected={
                "Inlet Dynamic Gas Pressure": "3.5 to 10.5 in. W.C. (Natural Gas)",
                "Flame Sensor Current": ">= 2.5 µA DC during steady combustion",
                "Igniter Transformer Output": "15 kV spark pulse",
                "Gas Solenoid Coils": "2.8 kΩ ± 10% resistance",
            },
            common_replacement_parts=[
                "Navien NPE Dual Flame Rod / Spark Electrode Kit (30010419A)",
                "Navien Gas Valve Assembly (30010420A)",
                "Navien Internal Condensate Trap Assembly",
            ],
            safety_warnings=[
                "Scalding water hazard: Turn off power before opening water filter or heat exchanger drain plugs.",
                "Gas pressure drop indicates inadequate pipe sizing (e.g. 1/2-inch line run too long).",
            ],
        ),
    },
    {
        "keywords": ["heat pump", "mini-split", "daikin", "mitsubishi", "e1", "e2", "e4", "defrost"],
        "guide": DiagnosticTroubleshootGuide(
            equipment_context="Inverter Heat Pump / Ductless Mini-Split (High Pressure / Sensor Error E1/E4)",
            probable_root_causes=[
                "Outdoor condenser coil matted with dirt/grass clippings causing high head pressure",
                "Outdoor DC inverter fan motor seized or blocked",
                "Outdoor coil defrost thermistor sensor open or out of calibration",
                "Electronic Expansion Valve (EEV) stepper motor stuck partially closed",
            ],
            step_by_step_test_procedure=[
                "Step 1: Check outdoor coil cleanliness and verify fan motor spins freely on command.",
                "Step 2: Unplug defrost coil thermistor from main inverter PCB; measure resistance with ohmmeter.",
                "Step 3: Compare resistance against temperature chart (target: ~10 kΩ at 77°F, ~30 kΩ at 32°F ice bath).",
                "Step 4: Check DC inverter bus voltage on PCB (caution: 320V - 380V DC on electrolytic capacitor bank).",
                "Step 5: Measure EEV coil winding resistances (typically 46 Ω across blue-red, orange-yellow pins).",
            ],
            multimeter_readings_expected={
                "Thermistor Sensor Resistance": "10.0 kΩ at 77°F / 32.5 kΩ at 32°F",
                "Inverter DC Bus Voltage": "320.0 VDC to 380.0 VDC (HIGH VOLTAGE)",
                "EEV Stepper Motor Coils": "46.0 Ω ± 4 Ω between coil phases",
                "Compressor Winding Balance": "0.4 Ω - 1.2 Ω balanced between U-V, V-W, W-U",
            },
            common_replacement_parts=[
                "Outdoor Coil Defrost Thermistor Harness",
                "Electronic Expansion Valve (EEV) Coil Assembly",
                "DC Inverter Fan Motor",
                "Main Outdoor Inverter Driver PCB",
            ],
            safety_warnings=[
                "CRITICAL: High Voltage DC Capacitor Bank holds 380V DC even after AC breaker is opened. Discharge before touching.",
                "R-410A / R-32 operating pressures exceed 450 PSI. Wear safety glasses and protective gloves.",
            ],
        ),
    },
]

# Standard trade universal fallback
UNIVERSAL_FALLBACK_GUIDE = DiagnosticTroubleshootGuide(
    equipment_context="Universal Field Diagnostic Isolation Protocol (HVAC / Plumbing / Electrical)",
    probable_root_causes=[
        "Loss of primary line voltage (120V / 240V) or blown control transformer fuse (3A / 5A)",
        "Open safety limit switch (float switch, high pressure switch, rollout switch)",
        "Sensor feedback out of operating range (thermistor, flame rod, pressure transducer)",
        "Motor capacitor degraded > 10% below rated microfarad (µF) rating",
    ],
    step_by_step_test_procedure=[
        "Step 1: Verify primary supply line voltage at disconnect with multimeter (120V/240V ± 10%).",
        "Step 2: Check 24VAC control transformer secondary: measure R to C on terminal board (target 24V - 28VAC).",
        "Step 3: Test safety limit circuit loop: verify continuity from 24V source through all series safety switches.",
        "Step 4: Test motor run capacitors with meter in MFD mode (must be within ±6% of stamped rating; replace if low).",
        "Step 5: Check amp draw under load with clamp-on ammeter against equipment data plate Full Load Amps (FLA).",
    ],
    multimeter_readings_expected={
        "Primary Line Voltage": "120.0 VAC / 240.0 VAC ± 10%",
        "Control Voltage Secondary": "24.0 VAC to 28.0 VAC",
        "Capacitor Tolerance": "±6% of rated MFD value",
        "Ground Continuity": "< 1.0 Ω chassis to ground rod",
    },
    common_replacement_parts=[
        "Universal 24V 40VA Control Transformer",
        "3-Amp / 5-Amp Automotive Blade Fuse (ATC/ATO)",
        "Dual Run Capacitor (45/5 µF 440 VAC)",
        "Universal Single-Pole 30A Contactor (24V coil)",
    ],
    safety_warnings=[
        "DANGER: Test for zero voltage before touching any electrical terminal. Lock-out / Tag-out (LOTO) active.",
        "Discharge capacitors with a 20k-ohm 5W resistor before handling.",
    ],
)


class FieldTechMentorService:
    """
    Field Tech AI Diagnostic Mentor & Fault Code Copilot.
    Provides on-site junior technicians with real-time multimeter test pinouts,
    diagnostic decision trees, and root cause analysis via Gemini 2.5 Flash and deterministic catalogs.
    """

    async def troubleshoot_equipment_fault(
        self,
        request: DiagnosticTroubleshootRequest,
    ) -> DiagnosticTroubleshootGuide:
        """
        Processes equipment brand, type, and fault code.
        Attempts Gemini 2.5 Flash structured diagnosis first, then falls back to trade fault catalog.
        """
        # 1. Attempt Gemini 2.5 Flash LLM diagnostic generation
        if settings.GEMINI_API_KEY:
            try:
                guide = await self._query_gemini_diagnostic(request)
                if guide:
                    return guide
            except Exception as exc:
                logger.warning(f"Gemini tech mentor query failed, using deterministic catalog: {exc}")

        # 2. Match against deterministic trade catalog
        search_terms = f"{request.equipment_brand} {request.equipment_type} {request.fault_code_or_symptom}".lower()
        if request.technician_notes:
            search_terms += f" {request.technician_notes.lower()}"

        best_match: Optional[DiagnosticTroubleshootGuide] = None
        max_matches = 0

        for item in DETERMINISTIC_FAULT_CATALOG:
            matches = sum(1 for kw in item["keywords"] if kw in search_terms)
            if matches > max_matches:
                max_matches = matches
                best_match = item["guide"]

        if best_match and max_matches >= 2:
            logger.info(f"Matched deterministic fault catalog ({max_matches} keywords) for '{request.fault_code_or_symptom}'")
            return best_match

        # 3. Return robust universal diagnostic isolation protocol
        logger.info(f"Using universal field diagnostic protocol for '{request.equipment_brand} {request.fault_code_or_symptom}'")
        return UNIVERSAL_FALLBACK_GUIDE

    async def _query_gemini_diagnostic(
        self,
        request: DiagnosticTroubleshootRequest,
    ) -> Optional[DiagnosticTroubleshootGuide]:
        """Queries Gemini 2.5 Flash with structured JSON output for field technician guidance."""
        try:
            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)

            prompt = (
                f"You are a Master HVAC, Plumbing, and Electrical Diagnostic Field Mentor assisting a field technician.\n"
                f"Equipment Brand: {request.equipment_brand}\n"
                f"Equipment Type: {request.equipment_type}\n"
                f"Reported Fault Code / Symptom: {request.fault_code_or_symptom}\n"
                f"Field Notes: {request.technician_notes or 'None'}\n\n"
                f"Provide a structured, step-by-step diagnostic guide for this exact issue. "
                f"Return ONLY valid JSON matching this schema:\n"
                f"{{\n"
                f'  "equipment_context": "string",\n'
                f'  "probable_root_causes": ["string"],\n'
                f'  "step_by_step_test_procedure": ["string"],\n'
                f'  "multimeter_readings_expected": {{"Target Metric": "Expected Value / Range"}},\n'
                f'  "common_replacement_parts": ["string"],\n'
                f'  "safety_warnings": ["string"]\n'
                f"}}"
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )

            raw_text = response.text.strip()
            # Strip markdown fences if present
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            data = json.loads(raw_text.strip())
            return DiagnosticTroubleshootGuide(**data)
        except Exception as err:
            logger.error(f"Gemini diagnostic model generation failed: {err}")
            return None


tech_mentor_service = FieldTechMentorService()
