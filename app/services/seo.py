"""Programmatic SEO & Local Organic Lead-Capture Engine.

Defines the 48-page DMV contractor solutions matrix covering:
4 Core Trades x 12 DMV Metro Hubs.
Generates localized metadata, pain points, average ticket benchmarks,
JSON-LD structured data, RFC-compliant XML sitemaps, and robots.txt.
"""

from typing import Dict, List, Optional, Any
import json
from urllib.parse import urljoin


TRADES: Dict[str, Dict[str, Any]] = {
    "plumbing": {
        "slug": "plumbing",
        "name": "Plumbing",
        "trade_type": "plumbing",
        "title_trade": "Emergency Plumbing",
        "badge": "24/7 AI Plumbing Dispatch",
        "icon": "🔧",
        "color": "sky",
        "primary_services": [
            "Emergency Pipe Bursts & Main Line Breaks",
            "Rapid Drain & Sewer Backup Clearing",
            "Emergency Water Heater Replacement & Leaks",
            "Sump Pump Failure & Sump Pit Overflow",
            "Commercial Restroom & Backflow Emergencies",
        ],
        "avg_ticket": 1200,
        "avg_ticket_formatted": "$1,200",
        "urgency_headline": "Burst pipes and sewer backups cannot wait for morning voicemail.",
        "typical_missed_calls_month": 14,
        "hero_tagline": "Capture high-margin pipe bursts, water heater failures, and main drain backflows before competitors answer.",
        "faqs": [
            {
                "q": "How does DispatchEngine detect real plumbing emergencies vs. routine drippy faucets?",
                "a": "Our conversational AI instantly asks the caller about active spraying water, shut-off valve status, and structural damage risk. If active flooding or raw sewage is detected, it bridges to your on-call plumber in <1.2 seconds. Routine fixture replacements are booked for regular business hours.",
            },
            {
                "q": "Can homeowners send photos of water heater model tags or broken supply lines?",
                "a": "Yes! While on the emergency call, DispatchEngine sends a secure 1-tap mobile link. The homeowner snaps a photo, and our computer vision extracts the water heater serial/model number, pipe material (PEX, copper, cast iron), and flooding severity before your technician arrives on site.",
            },
            {
                "q": "How quickly can our plumbing crews be set up with call forwarding?",
                "a": "Under 2 minutes. You receive a dedicated local forwarding number and standard carrier star-codes (*72 for Verizon, *21* for AT&T). Forward your after-hours line at 5 PM and your AI dispatcher takes over immediately.",
            },
            {
                "q": "How is this different from an answering service like Ruby or AnswerConnect?",
                "a": "Human call centers put callers on 3-minute hold, read rigid scripts, and cost $3-$5 per minute while still waking you up for non-emergencies. DispatchEngine answers simultaneously in 1.2s, qualifies severity, captures photos, and only bridges true emergencies.",
            },
        ],
    },
    "hvac": {
        "slug": "hvac",
        "name": "HVAC",
        "trade_type": "hvac",
        "title_trade": "24/7 Emergency HVAC & Heating/Cooling",
        "badge": "24/7 AI HVAC Dispatch",
        "icon": "❄️",
        "color": "amber",
        "primary_services": [
            "Sub-Zero Furnace & Boiler Lockout Diagnostics",
            "Extreme Heat AC Compressor & Coil Failures",
            "Dual-Fuel & Inverter Heat Pump Troubleshooting",
            "Condensate Overflow & Ceiling Leak Prevention",
            "Commercial Rooftop Unit (RTU) Emergency Service",
        ],
        "avg_ticket": 8500,
        "avg_ticket_formatted": "$8,500",
        "urgency_headline": "Mid-winter heat outages and peak-summer AC collapses drive immediate $8,500+ replacements.",
        "typical_missed_calls_month": 11,
        "hero_tagline": "Route frozen furnace alarms and blown compressors straight to your technicians with verified system photos.",
        "faqs": [
            {
                "q": "How does DispatchEngine triage freezing furnace lockouts vs. standard maintenance?",
                "a": "The AI screens for indoor temperature thresholds, household vulnerability (elderly, infants, pets), thermostat error codes, and electrical breaker status. Emergency heating outages trigger instant technician bridge calls, while standard tune-ups are scheduled cleanly into your calendar.",
            },
            {
                "q": "Can the AI identify condenser unit and furnace age from photos?",
                "a": "Yes. Homeowners upload a photo of the data plate. Our vision engine reads the manufacturer (Carrier, Trane, Lennox), ton size, SEER rating, and serial date code so your tech knows if it's a candidate for a same-day full system changeout.",
            },
            {
                "q": "Does DispatchEngine support multi-tier technician on-call rotations?",
                "a": "Yes. If your primary on-call HVAC tech doesn't accept the emergency bridge call within 30 seconds, DispatchEngine automatically escalates to your secondary lead tech, then to the service manager, ensuring zero lost emergency replacements.",
            },
            {
                "q": "Can it answer callers in Spanish for DMV bilingual homeowners?",
                "a": "Absolutely. DispatchEngine features autonomous bilingual detection with native Spanish voice synthesis (Lupe/Danielle), ensuring complete coverage across diverse regional homeowner bases.",
            },
        ],
    },
    "roofing": {
        "slug": "roofing",
        "name": "Roofing",
        "trade_type": "roofing",
        "title_trade": "Emergency Roof Tarping & Storm Damage",
        "badge": "24/7 AI Roofing Dispatch",
        "icon": "🏠",
        "color": "purple",
        "primary_services": [
            "Severe Storm Tree Strike & Attic Punctures",
            "Emergency Polyethylene Roof Tarping & Shrink-Wrap",
            "Wind-Sheared Shingle & Flashing Infiltration",
            "Commercial Flat Roof Membrane Ponding Leaks",
            "Insurance Scope of Loss & Dossier Documentation",
        ],
        "avg_ticket": 3200,
        "avg_ticket_formatted": "$3,200",
        "urgency_headline": "Active roof leaks during midnight rainstorms turn directly into lucrative full-roof insurance restorations.",
        "typical_missed_calls_month": 9,
        "hero_tagline": "Secure emergency tarping dispatches during high-wind storms and convert emergency callers into full insurance claims.",
        "faqs": [
            {
                "q": "How does DispatchEngine handle storm surge call volume spikes?",
                "a": "Unlike human dispatchers who get overwhelmed and busy-out lines during severe weather, DispatchEngine operates on serverless telecommunication infrastructure that answers 100+ simultaneous homeowner calls with zero queue wait times.",
            },
            {
                "q": "Does DispatchEngine capture storm damage photos for insurance claims?",
                "a": "Yes. While the homeowner is on the line, an SMS link prompts them to submit photos of attic leaks, water stains, and exterior roof damage. These photos are timestamped and compiled into a carrier-ready claim dossier.",
            },
            {
                "q": "Can we configure minimum job thresholds for emergency tarping?",
                "a": "Yes. You define your emergency service radius, dispatch fees, and tarping minimums in your tenant dashboard. The AI informs callers of your emergency dispatch terms before routing to your crews.",
            },
            {
                "q": "How fast does DispatchEngine connect emergency callers to our on-call foreman?",
                "a": "In under 1.2 seconds, the call is answered. Once the emergency criteria are verified (under 35 seconds), DispatchEngine initiates a live 3-way bridge call to your on-call supervisor's mobile phone.",
            },
        ],
    },
    "water-mitigation": {
        "slug": "water-mitigation",
        "name": "Water Mitigation",
        "trade_type": "water_mitigation",
        "title_trade": "Rapid Water Extraction & IICRC Drying",
        "badge": "24/7 AI Mitigation Dispatch",
        "icon": "💧",
        "color": "emerald",
        "primary_services": [
            "Category 3 Sewage Backflow Extraction",
            "High-Capacity Submersible Water Pump-Out",
            "IICRC S500 Psychrometric Chamber Drying Logs",
            "Thermal Imaging & Moisture Migration Mapping",
            "Direct Insurance Billing & Xactimate Scoping",
        ],
        "avg_ticket": 4500,
        "avg_ticket_formatted": "$4,500",
        "urgency_headline": "Every hour of standing water increases structural decay and mold risk. First responder gets the $4,500+ drying contract.",
        "typical_missed_calls_month": 12,
        "hero_tagline": "First contractor on-site wins the multi-room water restoration and reconstruction contract.",
        "faqs": [
            {
                "q": "How does DispatchEngine qualify IICRC Category 1, 2, and 3 water emergencies?",
                "a": "The conversational AI prompts callers on water origin (clean supply line, dishwasher discharge, or toilet/sewer backflow) and affected square footage. It classifies the IICRC water category and alerts your mitigation crew immediately.",
            },
            {
                "q": "Can the AI collect insurance policy and claim number information?",
                "a": "Yes. The AI collects the homeowner's insurance carrier (State Farm, USAA, Travelers, etc.), policy number, and adjuster contact info, populating your mitigation dossier before your extraction van even leaves the shop.",
            },
            {
                "q": "Does this integrate with mobile psychrometric moisture logs?",
                "a": "DispatchEngine tracks psychrometric drying milestones (ambient temp, relative humidity, grain depression) throughout the mitigation lifecycle, maintaining an auditable drying log for full insurance reimbursement.",
            },
            {
                "q": "Can our plumbing partners send emergency mitigation referrals through the platform?",
                "a": "Yes. DispatchEngine includes a B2B Partner Exchange with automated finder-fee tracking so local plumbers can dispatch water losses straight to your mitigation crews with 1 click.",
            },
        ],
    },
}


HUBS: Dict[str, Dict[str, Any]] = {
    "washington-dc": {
        "slug": "washington-dc",
        "city": "Washington",
        "state": "DC",
        "state_full": "District of Columbia",
        "region_label": "Washington, DC",
        "sub_areas": "Capitol Hill, Georgetown, Dupont Circle, Petworth, Adams Morgan, Navy Yard, Shaw, Tenleytown",
        "area_code": "202",
        "local_pain_points": (
            "Historic brick row homes with shared party walls, aging Victorian cast-iron plumbing prone to winter freeze breaks, "
            "rigid historic preservation commission guidelines, and high-density street parking that penalizes slow dispatch response times."
        ),
        "local_climate_context": "Vulnerable to freezing polar vortex snaps causing row home burst pipes, along with muggy subtropical summers causing high-volume HVAC condensate overflow leaks.",
        "region_group": "District of Columbia",
    },
    "arlington-va": {
        "slug": "arlington-va",
        "city": "Arlington",
        "state": "VA",
        "state_full": "Virginia",
        "region_label": "Arlington & Northern Virginia",
        "sub_areas": "Clarendon, Ballston, Rosslyn, Crystal City, Pentagon City, Shirlington, Cherrydale",
        "area_code": "703",
        "local_pain_points": (
            "High-density luxury mid-rises and condos requiring precise riser shut-off coordination, post-war brick homes with slab leak vulnerabilities, "
            "and severe summer humidity spikes that overwhelm residential HVAC coils."
        ),
        "local_climate_context": "Suburban urban corridor with intense commuter traffic along I-66 and Route 50 requiring dynamic GPS dispatch routing.",
        "region_group": "Northern Virginia",
    },
    "alexandria-va": {
        "slug": "alexandria-va",
        "city": "Alexandria",
        "state": "VA",
        "state_full": "Virginia",
        "region_label": "Alexandria & Old Town",
        "sub_areas": "Old Town, Del Ray, Rosemont, Kingstowne, Cameron Station, Potomac Yard",
        "area_code": "703",
        "local_pain_points": (
            "Potomac River tidal storm surge flooding, 18th- and 19th-century colonial plumbing infrastructures, "
            "and strict historic architectural board oversight on all exterior condenser and roof replacements."
        ),
        "local_climate_context": "Waterfront storm surge risks coupled with freezing winters make emergency mitigation and freeze protection essential.",
        "region_group": "Northern Virginia",
    },
    "fairfax-va": {
        "slug": "fairfax-va",
        "city": "Fairfax",
        "state": "VA",
        "state_full": "Virginia",
        "region_label": "Fairfax County",
        "sub_areas": "Fairfax City, Vienna, Reston, Herndon, Oakton, Burke, Annandale, Centreville",
        "area_code": "703",
        "local_pain_points": (
            "Extensive suburban territory spanning I-66 and Route 28, aging multi-level homes with failing original furnaces, "
            "and dense mature tree canopies causing severe wind-throw roof punctures during summer thunderstorms."
        ),
        "local_climate_context": "Sprawling family neighborhoods with high heating and cooling demands during seasonal weather extremes.",
        "region_group": "Northern Virginia",
    },
    "falls-church-va": {
        "slug": "falls-church-va",
        "city": "Falls Church",
        "state": "VA",
        "state_full": "Virginia",
        "region_label": "Falls Church & Pimmit",
        "sub_areas": "Broad Street Corridor, Pimmit Hills, Idylwood, Lake Barcroft, Bailey's Crossroads",
        "area_code": "703",
        "local_pain_points": (
            "Unique contrast between 1950s post-war cottages and newly constructed multi-million dollar luxury modern infill homes, "
            "requiring emergency dispatch capability for both vintage cast iron systems and modern high-efficiency heat pumps."
        ),
        "local_climate_context": "High-density residential pockets surrounding major commuter arteries requiring ultra-fast emergency crew arrival.",
        "region_group": "Northern Virginia",
    },
    "loudoun-va": {
        "slug": "loudoun-va",
        "city": "Loudoun County",
        "state": "VA",
        "state_full": "Virginia",
        "region_label": "Loudoun County / Dulles Corridor",
        "sub_areas": "Sterling, Leesburg, Ashburn, Dulles, Brambleton, Lansdowne, Purcellville",
        "area_code": "571",
        "local_pain_points": (
            "High-capacity residential estates featuring dual-fuel heat pumps and complex multi-zone HVAC dampers, "
            "data center power fluctuation stresses on AC components, and expansive geographic transit distances across Western Loudoun."
        ),
        "local_climate_context": "Piedmont foothills experience colder winter minimums and severe hail squalls along the Blue Ridge front.",
        "region_group": "Northern Virginia",
    },
    "bethesda-md": {
        "slug": "bethesda-md",
        "city": "Bethesda",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Bethesda & Chevy Chase",
        "sub_areas": "Chevy Chase, Downtown Bethesda, Bradley Hills, Glen Echo, Cabin John, Kenwood",
        "area_code": "301",
        "local_pain_points": (
            "Ultra-high-net-worth homeowners expecting instant, white-glove sub-2-minute emergency response, "
            "complex hydronic boiler radiant systems, and high-value finished basement estates demanding rapid water extraction."
        ),
        "local_climate_context": "Prime residential corridor where emergency homeowners hire the very first professional contractor who answers live.",
        "region_group": "Maryland Suburbs",
    },
    "silver-spring-md": {
        "slug": "silver-spring-md",
        "city": "Silver Spring",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Silver Spring & Takoma Park",
        "sub_areas": "Downtown Silver Spring, Takoma Park, Woodside, Four Corners, Colesville, Wheaton",
        "area_code": "301",
        "local_pain_points": (
            "Historic 1930s-1950s residential architecture with aging galvanized piping, municipal water pressure fluctuations causing supply line bursts, "
            "and frequent Sligo Creek basin flash-flood water backups."
        ),
        "local_climate_context": "High-density Montgomery County neighborhoods with older housing stock vulnerable to weather-induced plumbing and roof failures.",
        "region_group": "Maryland Suburbs",
    },
    "rockville-md": {
        "slug": "rockville-md",
        "city": "Rockville",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Rockville & I-270 Tech Corridor",
        "sub_areas": "Town Center, King Farm, Twinbrook, Fallsgrove, Woodmont, North Bethesda",
        "area_code": "301",
        "local_pain_points": (
            "Mixed residential communities and high-volume commercial tech facilities requiring fast emergency response, "
            "congested Route 355 traffic corridors, and aging municipal sewer tie-ins."
        ),
        "local_climate_context": "Suburban biotech hub where after-hours heating and cooling outages can jeopardize both home comfort and commercial facilities.",
        "region_group": "Maryland Suburbs",
    },
    "gaithersburg-md": {
        "slug": "gaithersburg-md",
        "city": "Gaithersburg",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Gaithersburg & Kentlands",
        "sub_areas": "Kentlands, Lakelands, Montgomery Village, Old Town Gaithersburg, Crown Farm",
        "area_code": "301",
        "local_pain_points": (
            "High concentration of neo-traditional planned communities with tight zero-lot-line townhouse roof setups, "
            "demanding HOAs with strict emergency repair standards, and intense summer attic heat degrading HVAC capacitors."
        ),
        "local_climate_context": "Dense townhouse clusters where an unaddressed plumbing leak or roof failure quickly damages adjacent neighbor properties.",
        "region_group": "Maryland Suburbs",
    },
    "prince-georges-md": {
        "slug": "prince-georges-md",
        "city": "Prince George's County",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Prince George's County & Bowie",
        "sub_areas": "Bowie, College Park, Laurel, Hyattsville, Upper Marlboro, Greenbelt, Oxon Hill",
        "area_code": "240",
        "local_pain_points": (
            "Broad geographic territory traversing the Capital Beltway, high frequency of intense summer squall line tree impacts on roofing, "
            "and older clay tile municipal sewer lines prone to stormwater root backups."
        ),
        "local_climate_context": "Frequent severe storm watches and thunderstorm cells bringing sudden flood and wind damage emergency spikes.",
        "region_group": "Maryland Suburbs",
    },
    "annapolis-md": {
        "slug": "annapolis-md",
        "city": "Annapolis",
        "state": "MD",
        "state_full": "Maryland",
        "region_label": "Annapolis & Anne Arundel County",
        "sub_areas": "Historic Annapolis, Eastport, Arnold, Severna Park, Edgewater, Cape St. Claire",
        "area_code": "410",
        "local_pain_points": (
            "Chesapeake Bay maritime climate with salt air corrosion on exterior HVAC coils and roof metal flashings, "
            "extremely high water table conditions causing sump pump failures during nor'easters, and historic harbor district access constraints."
        ),
        "local_climate_context": "Coastal storm surges and high humidity demand rapid 24/7 moisture mitigation and emergency water extraction.",
        "region_group": "Maryland Suburbs",
    },
}


class SEOService:
    """Provides metadata, structured schemas, sitemap generation, and robots.txt

    for all 48 programmatic trade x hub landing pages.
    """

    @classmethod
    def get_slug(cls, trade_key: str, hub_key: str) -> str:
        """Format the canonical page slug: {trade}-dispatch-{city}."""
        return f"{trade_key}-dispatch-{hub_key}"

    @classmethod
    def parse_slug(cls, slug: str) -> Optional[tuple[str, str]]:
        """Parse a slug into (trade_key, hub_key) if valid."""
        for t_key in TRADES:
            prefix = f"{t_key}-dispatch-"
            if slug.startswith(prefix):
                h_key = slug[len(prefix):]
                if h_key in HUBS:
                    return t_key, h_key
        return None

    @classmethod
    def get_page_data(cls, slug: str, base_url: str = "https://dispatchengine-production.up.railway.app") -> Optional[Dict[str, Any]]:
        """Retrieve full SEO and presentation dictionary for a specific page slug."""
        parsed = cls.parse_slug(slug)
        if not parsed:
            return None

        trade_key, hub_key = parsed
        trade = TRADES[trade_key]
        hub = HUBS[hub_key]

        canonical_url = f"{base_url.rstrip('/')}/solutions/{slug}"
        city_display = f"{hub['city']}, {hub['state']}"

        # Localized Title & Meta Description
        meta_title = f"24/7 {trade['title_trade']} Dispatch Software in {city_display} | DispatchEngine"
        meta_desc = (
            f"Stop losing after-hours {trade['name'].lower()} emergencies in {city_display}. "
            f"DispatchEngine answers homeowner calls in 1.2s, qualifies emergencies, captures photos, "
            f"and dispatches on-call technicians before competitors pick up."
        )

        # JSON-LD Schema
        schema_data = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "SoftwareApplication",
                    "@id": f"{canonical_url}#software",
                    "name": f"DispatchEngine AI Dispatcher for {trade['name']} in {city_display}",
                    "applicationCategory": "BusinessApplication",
                    "operatingSystem": "Cloud / Web / iOS / Android",
                    "description": meta_desc,
                    "url": canonical_url,
                    "offers": {
                        "@type": "Offer",
                        "price": "149.00",
                        "priceCurrency": "USD",
                        "availability": "https://schema.org/InStock",
                    },
                },
                {
                    "@type": "Service",
                    "@id": f"{canonical_url}#service",
                    "name": f"24/7 Autonomous {trade['name']} Dispatch & Triage",
                    "serviceType": f"Emergency {trade['name']} Call Answering & Dispatch",
                    "provider": {
                        "@type": "Organization",
                        "name": "DispatchEngine",
                        "url": base_url,
                        "logo": f"{base_url}/static/img/logo.png",
                    },
                    "areaServed": {
                        "@type": "AdministrativeArea",
                        "name": city_display,
                    },
                    "hasOfferCatalog": {
                        "@type": "OfferCatalog",
                        "name": f"{trade['name']} Emergency Services",
                        "itemListElement": [
                            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": svc}}
                            for svc in trade["primary_services"]
                        ],
                    },
                },
                {
                    "@type": "BreadcrumbList",
                    "@id": f"{canonical_url}#breadcrumbs",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": base_url},
                        {"@type": "ListItem", "position": 2, "name": "Solutions", "item": f"{base_url}/solutions"},
                        {"@type": "ListItem", "position": 3, "name": f"{trade['name']} in {hub['city']}", "item": canonical_url},
                    ],
                },
            ],
        }

        # Calculate estimated monthly missed revenue
        estimated_monthly_leak = trade["typical_missed_calls_month"] * trade["avg_ticket"]

        return {
            "slug": slug,
            "canonical_url": canonical_url,
            "meta_title": meta_title,
            "meta_description": meta_desc,
            "json_ld_schema": json.dumps(schema_data),
            "trade": trade,
            "hub": hub,
            "city_display": city_display,
            "headline": f"The 24/7 Autonomous AI Dispatcher for {trade['name']} Contractors in {city_display}",
            "subhead": (
                f"Answer after-hours homeowner calls in under 1.2 seconds, capture equipment photos, "
                f"and dispatch your on-call {hub['city']} crews before competitors pick up."
            ),
            "estimated_monthly_leak_formatted": f"${estimated_monthly_leak:,.0f}",
            "nearby_hubs": cls._get_nearby_hubs(hub_key, trade_key),
            "cross_trades": cls._get_cross_trades(trade_key, hub_key),
        }

    @classmethod
    def _get_nearby_hubs(cls, current_hub_key: str, trade_key: str) -> List[Dict[str, str]]:
        """Return other hubs for the same trade to maximize internal link graph."""
        current_state = HUBS[current_hub_key]["state"]
        nearby = []
        for h_key, h_data in HUBS.items():
            if h_key != current_hub_key:
                nearby.append({
                    "title": f"{TRADES[trade_key]['name']} in {h_data['city']}, {h_data['state']}",
                    "url": f"/solutions/{cls.get_slug(trade_key, h_key)}",
                    "city": h_data["city"],
                    "state": h_data["state"],
                })
        return nearby[:6]

    @classmethod
    def _get_cross_trades(cls, current_trade_key: str, hub_key: str) -> List[Dict[str, str]]:
        """Return other trades in the same hub for cross-linking."""
        cross = []
        for t_key, t_data in TRADES.items():
            if t_key != current_trade_key:
                cross.append({
                    "title": f"{t_data['name']} Dispatch in {HUBS[hub_key]['city']}",
                    "url": f"/solutions/{cls.get_slug(t_key, hub_key)}",
                    "trade_name": t_data["name"],
                    "icon": t_data["icon"],
                })
        return cross

    @classmethod
    def get_all_pages(cls, base_url: str = "https://dispatchengine-production.up.railway.app") -> List[Dict[str, Any]]:
        """Return all 48 programmatic SEO pages."""
        pages = []
        for t_key in TRADES:
            for h_key in HUBS:
                slug = cls.get_slug(t_key, h_key)
                page_data = cls.get_page_data(slug, base_url=base_url)
                if page_data:
                    pages.append(page_data)
        return pages

    @classmethod
    def get_matrix_by_category(cls) -> Dict[str, Any]:
        """Organize matrix by trade and regional group for the /solutions directory hub."""
        by_trade = {}
        for t_key, t_data in TRADES.items():
            by_trade[t_key] = {
                "trade": t_data,
                "pages": [
                    {
                        "slug": cls.get_slug(t_key, h_key),
                        "url": f"/solutions/{cls.get_slug(t_key, h_key)}",
                        "city": h_data["city"],
                        "state": h_data["state"],
                        "region_label": h_data["region_label"],
                        "region_group": h_data["region_group"],
                    }
                    for h_key, h_data in HUBS.items()
                ],
            }

        by_region = {
            "District of Columbia": [],
            "Northern Virginia": [],
            "Maryland Suburbs": [],
        }

        for h_key, h_data in HUBS.items():
            region = h_data["region_group"]
            hub_entry = {
                "hub": h_data,
                "trades": [
                    {
                        "trade_name": t_data["name"],
                        "icon": t_data["icon"],
                        "slug": cls.get_slug(t_key, h_key),
                        "url": f"/solutions/{cls.get_slug(t_key, h_key)}",
                    }
                    for t_key, t_data in TRADES.items()
                ],
            }
            if region in by_region:
                by_region[region].append(hub_entry)

        return {
            "by_trade": by_trade,
            "by_region": by_region,
            "total_pages": len(TRADES) * len(HUBS),
        }

    @classmethod
    def generate_sitemap_xml(cls, base_url: str = "https://dispatchengine-production.up.railway.app") -> str:
        """Generate RFC-compliant XML sitemap indexing all 48 solution pages plus core pages."""
        base = base_url.rstrip("/")

        static_urls = [
            {"loc": f"{base}/", "priority": "1.0", "changefreq": "daily"},
            {"loc": f"{base}/solutions", "priority": "0.9", "changefreq": "daily"},
            {"loc": f"{base}/audit", "priority": "0.8", "changefreq": "weekly"},
            {"loc": f"{base}/widget-demo", "priority": "0.8", "changefreq": "weekly"},
            {"loc": f"{base}/onboard", "priority": "0.9", "changefreq": "weekly"},
        ]

        solution_urls = []
        for t_key in TRADES:
            for h_key in HUBS:
                slug = cls.get_slug(t_key, h_key)
                solution_urls.append({
                    "loc": f"{base}/solutions/{slug}",
                    "priority": "0.8",
                    "changefreq": "weekly",
                })

        all_urls = static_urls + solution_urls

        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]

        for item in all_urls:
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{item['loc']}</loc>")
            xml_lines.append(f"    <changefreq>{item['changefreq']}</changefreq>")
            xml_lines.append(f"    <priority>{item['priority']}</priority>")
            xml_lines.append("  </url>")

        xml_lines.append("</urlset>")
        return "\n".join(xml_lines)

    @classmethod
    def generate_robots_txt(cls, base_url: str = "https://dispatchengine-production.up.railway.app") -> str:
        """Generate clean robots.txt pointing to sitemap.xml."""
        base = base_url.rstrip("/")
        return (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /api/\n"
            "Disallow: /docs\n"
            "Disallow: /redoc\n"
            "Disallow: /openapi.json\n\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )
