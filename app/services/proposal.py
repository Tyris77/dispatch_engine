from typing import Any, Dict, List, Optional
from app.core.logging import logger
from app.schemas.proposal import ProposalEstimate, ProposalOption
from app.schemas.vision import EquipmentDiagnosticReport


class ProposalService:
    """
    Autonomous Good-Better-Best tiered proposal generation engine.
    Calculates dynamic pricing, scope of work, warranty tiers, and required deposits
    based on multimodal vision diagnostics, equipment data plates, and contractor rate cards.
    """

    TRADE_TEMPLATES: Dict[str, Dict[str, Any]] = {
        "hvac": {
            "keywords": ["hvac", "condenser", "ac", "air conditioner", "heat pump", "compressor", "chiller"],
            "bronze": {
                "title": "Precision Component Repair & Rebuild",
                "base_price": 545.0,
                "scope_bullets": [
                    "Replace failing dual-run capacitor and contactor switch",
                    "Chemical clean & straighten exterior condenser coil fins",
                    "Verify subcooling/superheat and optimize refrigerant pressure",
                    "Safety inspection of wiring, contact points, and disconnect box",
                ],
                "warranty_info": "1-Year Parts & Labor Craftsmanship Warranty",
                "badge": "BUDGET FRIENDLY",
            },
            "silver": {
                "title": "Standard High-Efficiency System Replacement",
                "base_price": 7200.0,
                "scope_bullets": [
                    "Install complete code-compliant matched system",
                    "New composite equipment pad, vibration dampeners, and surge protector",
                    "Digital programmable touchscreen thermostat included",
                    "R-454B/R-32 eco-friendly refrigerant charge and EPA certification",
                    "Includes complete removal and recycling of old equipment",
                ],
                "warranty_info": "10-Year Equipment Parts + 2-Year Full Workmanship",
                "badge": "RECOMMENDED - BEST VALUE",
            },
            "gold": {
                "title": "Ultra-Quiet Inverter Variable-Speed Climate System",
                "base_price": 13800.0,
                "scope_bullets": [
                    "Top-tier variable-speed inverter compressor (up to 20+ SEER2)",
                    "Whisper-quiet acoustic dampening (as low as 54 dBA)",
                    "Smart Wi-Fi communicating thermostat with remote smartphone control",
                    "Hospital-grade whole-home indoor air quality filtration system",
                    "Annual 21-point precision tune-up & priority VIP dispatch for 3 years",
                ],
                "warranty_info": "12-Year Extended Bumper-to-Bumper + 5-Year Maintenance Plan",
                "badge": "MAX EFFICIENCY & COMFORT",
            },
        },
        "plumbing": {
            "keywords": ["plumb", "pipe", "water heater", "leak", "tank", "valve", "drain", "sewer"],
            "bronze": {
                "title": "Targeted Rebuild & Leak Mitigation",
                "base_price": 420.0,
                "scope_bullets": [
                    "Replace failed temperature & pressure relief valve (T&P)",
                    "Anode rod inspection & full sediment purge flush",
                    "Replace corroded brass dielectric unions and supply fittings",
                    "Static and dynamic water pressure safety diagnostic",
                ],
                "warranty_info": "1-Year Parts & Labor Craftsmanship Warranty",
                "badge": "IMMEDIATE REPAIR",
            },
            "silver": {
                "title": "Standard Energy-Star Water Heater Replacement",
                "base_price": 2650.0,
                "scope_bullets": [
                    "Install 50-gallon commercial-grade high recovery water heater",
                    "Thermal expansion tank and emergency automatic water shutoff ball valve",
                    "New earthquake strapping / seismic restraint kit (local code compliant)",
                    "Complete disposal of old water heater and job site sanitation",
                ],
                "warranty_info": "6-Year Tank & Parts + 2-Year Full Labor Warranty",
                "badge": "MOST POPULAR",
            },
            "gold": {
                "title": "Continuous Tankless On-Demand Water Heating Solution",
                "base_price": 6200.0,
                "scope_bullets": [
                    "Endless hot water tankless system (up to 11.2 GPM high efficiency)",
                    "Direct concentric PVC/polypropylene venting to exterior",
                    "Integrated high-speed recirculation pump for instant hot water at faucets",
                    "Includes premium scale-prevention filter system and isolation valves",
                    "5-Year annual descaling maintenance checkups included",
                ],
                "warranty_info": "15-Year Heat Exchanger + 5-Year Comprehensive Labor",
                "badge": "ENDLESS HOT WATER",
            },
        },
        "electrical": {
            "keywords": ["electric", "panel", "breaker", "wire", "service", "conduit", "fuse"],
            "bronze": {
                "title": "Bus Bar & Breaker Reconditioning",
                "base_price": 580.0,
                "scope_bullets": [
                    "Replace scorched or overloaded branch circuit breaker",
                    "Torque all terminal lugs to NEC specification with calibrated tools",
                    "Whole-home surge protection device (SPD) installation at main",
                    "Infrared thermal imaging scan to detect hidden resistance hotspots",
                ],
                "warranty_info": "1-Year Parts & Labor Craftsmanship Warranty",
                "badge": "SAFETY TUNE-UP",
            },
            "silver": {
                "title": "200-Amp Code-Compliant Modernization Upgrade",
                "base_price": 3850.0,
                "scope_bullets": [
                    "Install new 200-Amp 40-circuit outdoor/indoor main distribution panel",
                    "New service entrance copper conductors and utility meter socket",
                    "Dual 8-foot copper grounding rods bonded with #4 bare copper",
                    "Arc-Fault (AFCI) and Dual-Function GFCI breaker protection on required circuits",
                    "Utility coordination, municipal permitting, and final city inspection pass",
                ],
                "warranty_info": "10-Year Equipment + 3-Year Craftsmanship Warranty",
                "badge": "RECOMMENDED UPGRADE",
            },
            "gold": {
                "title": "Smart Connected Energy Panel & Backup Ready Infrastructure",
                "base_price": 8600.0,
                "scope_bullets": [
                    "Smart architectural breaker panel with circuit-level power monitoring",
                    "Real-time mobile app control to shed loads and monitor kilowatt consumption",
                    "Dedicated Level-2 (48A/240V) Electric Vehicle (EV) charging circuit",
                    "Integrated whole-home battery backup / solar generator transfer interface",
                    "Lifetime workmanship guarantee and 24/7 priority electrical dispatch",
                ],
                "warranty_info": "12-Year Smart Panel Parts + Lifetime Craftsmanship",
                "badge": "FUTURE PROOF",
            },
        },
        "roofing": {
            "keywords": ["roof", "shingle", "flashing", "chimney", "gutter", "skylight", "tile"],
            "bronze": {
                "title": "Targeted Leak Seal & Flashing Restoration",
                "base_price": 650.0,
                "scope_bullets": [
                    "Replace damaged shingles with color-matched architectural replacements",
                    "Re-flash and reseal plumbing vent boots with elastomeric neoprene sleeves",
                    "Seal and secure loose step flashing and counter-flashing with urethane sealant",
                    "Full roof water-shedding inspection and debris cleanout along valleys",
                ],
                "warranty_info": "1-Year Leak-Free Craftsmanship Warranty",
                "badge": "EMERGENCY LEAK STOP",
            },
            "silver": {
                "title": "Architectural 30-Year Dimensional Roof System",
                "base_price": 10500.0,
                "scope_bullets": [
                    "Complete tear-off of existing roofing down to clean decking",
                    "Install commercial synthetic water-shedding underlayment",
                    "Self-adhering ice & water shield in valleys, eaves, and penetrations",
                    "Install 30-year lifetime architectural laminate shingles (130 MPH wind rated)",
                    "Continuous ridge vent ventilation system with magnetic sweep cleanup",
                ],
                "warranty_info": "30-Year Manufacturer Material + 5-Year Workmanship Warranty",
                "badge": "MOST POPULAR",
            },
            "gold": {
                "title": "Class-4 Impact-Resistant Lifetime Armor Roof System",
                "base_price": 17800.0,
                "scope_bullets": [
                    "Class 4 UL 2218 impact-resistant composite/metal shingle system (insurance discounts)",
                    "Premium breathable ice & water shield installed 100% across critical rakes and eaves",
                    "Custom 26-gauge powder-coated drip edge and seamless aluminum flashing package",
                    "Solar-powered smart attic ventilation fan for optimal energy efficiency",
                    "Transferable 50-year non-prorated manufacturer warranty",
                ],
                "warranty_info": "50-Year Non-Prorated Warranty + 15-Year Leak-Free Workmanship",
                "badge": "LIFETIME PROTECTION",
            },
        },
    }

    GENERIC_TEMPLATE: Dict[str, Any] = {
        "bronze": {
            "title": "Precision Component Repair & Restoration",
            "base_price": 495.0,
            "scope_bullets": [
                "Recondition failing components to restore immediate operation",
                "Calibrate safety controls and verify electrical/mechanical specs",
                "Clean critical wear points and test under normal operating load",
            ],
            "warranty_info": "1-Year Labor & Replacement Parts Warranty",
            "badge": "TARGETED FIX",
        },
        "silver": {
            "title": "Complete Modern System Replacement",
            "base_price": 4800.0,
            "scope_bullets": [
                "Install brand-new high-efficiency matched replacement equipment",
                "Code-compliant connections, safety shutoffs, and mounting hardware",
                "Complete removal, recycling, and hauling away of old equipment",
                "Full operational walkthrough and multi-point commissioning check",
            ],
            "warranty_info": "10-Year Manufacturer Equipment + 2-Year Labor Warranty",
            "badge": "RECOMMENDED",
        },
        "gold": {
            "title": "Premium Enterprise High-Efficiency System",
            "base_price": 9400.0,
            "scope_bullets": [
                "Commercial-grade ultra-efficiency model with extended duty cycle",
                "Smart remote digital monitoring and priority telemetry interface",
                "Surge and environmental protection package included",
                "Annual preventative inspection package included for 3 years",
            ],
            "warranty_info": "15-Year Comprehensive Extended Coverage",
            "badge": "PREMIUM COMFORT",
        },
    }

    def _determine_trade_template(self, equipment_type: str) -> Dict[str, Any]:
        """Matches equipment category string against trade templates."""
        eq_lower = equipment_type.lower()
        for trade_key, data in self.TRADE_TEMPLATES.items():
            if any(keyword in eq_lower for keyword in data["keywords"]):
                return data
        return self.GENERIC_TEMPLATE

    def generate_tiered_proposal(
        self,
        diagnostic: Optional[EquipmentDiagnosticReport] = None,
        tenant_settings: Optional[Dict[str, Any]] = None,
    ) -> ProposalEstimate:
        """
        Dynamically generates 3 competitive tiers (Bronze, Silver, Gold) matching
        the diagnosed equipment, brand manufacturer, damage assessment, and contractor rate card.
        """
        settings = tenant_settings or {}
        markup_multiplier = float(settings.get("pricing_markup_multiplier", 1.0))
        deposit_pct = float(settings.get("deposit_percentage", 25.0))

        if diagnostic:
            eq_type = diagnostic.equipment_type
            brand = diagnostic.brand_manufacturer
            model = diagnostic.model_number
            damage = diagnostic.damage_assessment
            parts = diagnostic.recommended_parts_tools

            equipment_summary_parts = [f"{brand} {eq_type}" if brand else eq_type]
            if model and model != "N/A":
                equipment_summary_parts.append(f"Model: {model}")
            equipment_summary_parts.append(f"Diagnosed Issue: {damage}")
            equipment_summary = " | ".join(equipment_summary_parts)

            template = self._determine_trade_template(eq_type)
        else:
            eq_type = "Mechanical System"
            brand = None
            damage = "General wear & component malfunction"
            parts = []
            equipment_summary = "Equipment Diagnostic: Standard Service & Modernization Options"
            template = self.GENERIC_TEMPLATE

        # 1. Bronze Option (Repair / Patch)
        bronze_raw = template["bronze"]
        bronze_bullets = list(bronze_raw["scope_bullets"])
        if parts:
            bronze_bullets.insert(0, f"Install required parts: {', '.join(parts[:2])}")
        if damage and diagnostic:
            bronze_bullets.append(f"Address identified symptom: {damage}")

        bronze_price = round(bronze_raw["base_price"] * markup_multiplier, 2)
        bronze_title = f"{bronze_raw['title']}"
        if brand:
            bronze_title = f"{brand} {bronze_title}"

        from app.services.rebates import rebates_service
        bronze_rebates = rebates_service.calculate_applicable_rebates(eq_type, "Good", bronze_price, settings)

        bronze_option = ProposalOption(
            tier_name="Repair / Patch",
            title=bronze_title,
            price_estimate=bronze_price,
            scope_bullets=bronze_bullets[:5],
            warranty_info=bronze_raw["warranty_info"],
            badge=bronze_raw.get("badge"),
            rebates_available=bronze_rebates.total_rebates_available,
            net_investment=bronze_rebates.net_customer_investment,
        )

        # 2. Silver Option (Standard Replacement)
        silver_raw = template["silver"]
        silver_bullets = list(silver_raw["scope_bullets"])
        silver_price = round(silver_raw["base_price"] * markup_multiplier, 2)
        silver_title = silver_raw["title"]
        if brand:
            silver_title = f"New {brand} {silver_title}"

        silver_rebates = rebates_service.calculate_applicable_rebates(eq_type, "Better", silver_price, settings)

        silver_option = ProposalOption(
            tier_name="Standard Replacement",
            title=silver_title,
            price_estimate=silver_price,
            scope_bullets=silver_bullets,
            warranty_info=silver_raw["warranty_info"],
            badge=silver_raw.get("badge", "RECOMMENDED"),
            rebates_available=silver_rebates.total_rebates_available,
            net_investment=silver_rebates.net_customer_investment,
        )

        # 3. Gold Option (Premium System)
        gold_raw = template["gold"]
        gold_bullets = list(gold_raw["scope_bullets"])
        gold_price = round(gold_raw["base_price"] * markup_multiplier, 2)
        gold_title = gold_raw["title"]
        if brand:
            gold_title = f"Top-Tier {brand} {gold_title}"

        gold_rebates = rebates_service.calculate_applicable_rebates(eq_type, "Best", gold_price, settings)

        gold_option = ProposalOption(
            tier_name="Premium System",
            title=gold_title,
            price_estimate=gold_price,
            scope_bullets=gold_bullets,
            warranty_info=gold_raw["warranty_info"],
            badge=gold_raw.get("badge"),
            rebates_available=gold_rebates.total_rebates_available,
            net_investment=gold_rebates.net_customer_investment,
        )

        # Deposit is computed from the recommended Silver tier
        deposit_required = round(silver_price * (deposit_pct / 100.0), 2)

        return ProposalEstimate(
            equipment_summary=equipment_summary,
            options=[bronze_option, silver_option, gold_option],
            deposit_required=deposit_required,
            deposit_percentage=deposit_pct,
        )

    def calculate_membership_offer(
        self,
        tier_price: float,
        tenant_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Computes the instant membership savings on a given proposal tier price.
        Extracts plan configuration from tenant.settings['membership_plans']
        or defaults to high-converting 15% VIP Care Club ($19.99/mo).
        """
        settings = tenant_settings or {}
        plans = settings.get("membership_plans")
        if plans and isinstance(plans, list) and len(plans) > 0:
            plan = plans[0]
        else:
            plan = {
                "name": "Comfort Club VIP",
                "monthly_price": 19.99,
                "discount_pct": 15.0,
                "perks": [
                    "15% Off Today's Repair & All Future Services",
                    "$0 Emergency Diagnostic & Trip Fee",
                    "Annual 21-Point System Precision Tune-Up Included",
                    "Front-of-the-Line Priority VIP Dispatch",
                ],
                "billing_interval": "monthly",
            }

        discount_pct = float(plan.get("discount_pct", 15.0))
        monthly_price = float(plan.get("monthly_price", 19.99))
        discount_amount = round(tier_price * (discount_pct / 100.0), 2)
        discounted_price = round(max(0.0, tier_price - discount_amount), 2)
        deposit_pct = float(settings.get("deposit_percentage", 25.0))
        discounted_deposit = round(discounted_price * (deposit_pct / 100.0), 2)
        first_year_savings = round(discount_amount + 149.0, 2)

        return {
            "plan": plan,
            "plan_name": plan.get("name", "Comfort Club VIP"),
            "monthly_price": monthly_price,
            "discount_pct": discount_pct,
            "discount_amount": discount_amount,
            "original_price": tier_price,
            "discounted_price": discounted_price,
            "deposit_required": discounted_deposit,
            "first_year_savings": first_year_savings,
            "perks": plan.get("perks", []),
        }


proposal_service = ProposalService()
generate_tiered_proposal = proposal_service.generate_tiered_proposal
calculate_membership_offer = proposal_service.calculate_membership_offer
