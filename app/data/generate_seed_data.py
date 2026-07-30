"""
Purpose: Generate a research-grounded synthetic infrastructure/SaaS spend portfolio for PACT.

This is a one-time (re-runnable, deterministic) generator, not part of the runtime app.
It produces the CSV fixtures under app/data/seed/ and the realistic contract prose
under app/data/contract_docs/, which app/data/seed_db.py then loads at app startup.

Pricing bands are grounded in 2026 market research (colocation, telecom circuit,
SaaS, and enterprise mobility benchmarks) rather than arbitrary numbers - see
docs/architecture.md for sources. All vendor names are fictional.

Run: python app/data/generate_seed_data.py
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

SEED_DIR = Path(__file__).resolve().parent / "seed"
DOCS_DIR = Path(__file__).resolve().parent / "contract_docs"
TODAY = date(2026, 7, 30)

# ---------------------------------------------------------------------------
# Vendor name pools (all fictional)
# ---------------------------------------------------------------------------

TELECOM_VENDORS = [
    "TelNet Communications", "MetroWave Networks", "NorthPoint Fiber",
    "Continental Circuit Co", "Backbone Systems", "Vertex Telecom",
    "Lattice Networks", "Ridgeline Connect", "Pinnacle Wireline", "Trueline Carrier",
]
COLO_VENDORS = [
    "Latticework Data Centers", "Ironhold Colocation", "Meridian Data Centers",
    "Basecamp Colo", "Anchor Point Data Centers", "Substation Colocation",
]
SAAS_VENDORS = {
    "Identity & Access": ["Vaultkey Identity", "Keystone IAM", "Gatepost Access"],
    "Productivity Suite": ["Cascade Productivity", "Brightline Workspace", "Openfield Docs"],
    "Security - Endpoint": ["CyberSecure", "Overwatch Security", "Sentrywall"],
    "Observability": ["Pulsepoint Observability", "Northstar Analytics"],
    "DevOps Platform": ["Flowstate DevOps", "Forgeline CI/CD"],
    "CRM / ERP": ["Bridgeform CRM", "Compass ERP"],
    "HR / Finance": ["Brightline HR", "Fernwood People Ops"],
    "AI / LLM Assistant": ["Nimbus AI", "CogniStack AI", "Synapse Copilot"],
}
MOBILE_VENDORS = ["MobileOne", "AirBridge Wireless", "Continental Mobile", "Skylark Mobile", "Union Wireless"]
UC_VENDORS = ["VoiceBridge", "Ringform Communications", "Dialtown UC"]
SUPPORT_VENDORS = ["DataSphere Managed Services", "Sentinel Grid MDR", "Recovery Point DR Services", "Watchtower Support"]

OWNERS = [
    "Alex Ramos", "Jamie Chen", "Sarah Lee", "Chris Kim", "Ash Patel", "Taylor Grant",
    "Monica Ruiz", "Devon Brooks", "Priya Nair", "Sam O'Connor", "Morgan Yee", "Elena Popescu",
]
REGIONS = ["US-East", "US-West", "US-Central", "EMEA", "APAC"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_contract_seq = 0


def next_contract_id() -> str:
    global _contract_seq
    _contract_seq += 1
    return f"C-{_contract_seq:04d}"


def rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


def owner_or_blank(missing_rate: float) -> str:
    return "" if random.random() < missing_rate else random.choice(OWNERS)


@dataclass
class Contract:
    contract_id: str
    vendor: str
    service_type: str
    start_date: date
    end_date: date
    annual_cost: float
    monthly_cost: float
    auto_renew: str
    notice_days: int
    termination_fee_pct: int
    escalation_pct: int
    owner: str
    status: str = "Active"
    region: str = "US-East"
    minimum_commitment: str = ""


CONTRACTS: list[Contract] = []


def pick_renewal_bucket() -> str:
    """~14% of contracts land in a near-term renewal window; the rest renew
    6 months to 4 years out, so 'active' contracts never carry a stale/past
    end date and HIGH renewal risk stays a meaningful, minority signal."""
    r = random.random()
    if r < 0.04:
        return "30d"
    if r < 0.08:
        return "60d"
    if r < 0.14:
        return "90d"
    return "normal"


def make_contract(vendor: str, service_type: str, monthly_cost: float, *, region: str | None = None,
                   term_years: float = 3, notice_days: int | None = None,
                   termination_fee_pct: int | None = None, escalation_pct: int | None = None,
                   minimum_commitment: str = "", renewal_bucket: str = "auto",
                   missing_owner_rate: float = 0.12) -> Contract:
    cid = next_contract_id()
    monthly_cost = round(monthly_cost, 2)
    annual_cost = round(monthly_cost * 12, 2)

    bucket = pick_renewal_bucket() if renewal_bucket == "auto" else renewal_bucket
    if bucket == "30d":
        end = TODAY + timedelta(days=random.randint(5, 30))
    elif bucket == "60d":
        end = TODAY + timedelta(days=random.randint(31, 60))
    elif bucket == "90d":
        end = TODAY + timedelta(days=random.randint(61, 90))
    else:
        # always resolves to a future end date - never an already-expired "Active" contract
        end = TODAY + timedelta(days=random.randint(180, 1500))
    start = end - timedelta(days=int(365 * term_years))

    return Contract(
        contract_id=cid,
        vendor=vendor,
        service_type=service_type,
        start_date=start,
        end_date=end,
        annual_cost=annual_cost,
        monthly_cost=monthly_cost,
        auto_renew=random.choice(["Yes", "Yes", "No"]),
        notice_days=notice_days or random.choice([30, 45, 60, 90]),
        termination_fee_pct=termination_fee_pct if termination_fee_pct is not None else random.choice([5, 8, 10, 12, 15, 18, 20, 25]),
        escalation_pct=escalation_pct if escalation_pct is not None else random.choice([2, 3, 3, 4, 5, 6]),
        owner=owner_or_blank(missing_owner_rate),
        region=region or random.choice(REGIONS),
        minimum_commitment=minimum_commitment,
    )


# ---------------------------------------------------------------------------
# 1. Telecom circuit contracts + circuits
# ---------------------------------------------------------------------------

CIRCUIT_TIERS = [
    # (label, bandwidth_mbps range, $/Mbps/month benchmark-ish range)
    ("DIA-100", (80, 150), (3.5, 5.5)),
    ("DIA-500", (400, 600), (2.0, 3.2)),
    ("DIA-1000", (900, 1200), (1.1, 1.8)),
    ("MPLS-Backbone", (2000, 10000), (0.35, 0.65)),
    ("Point-to-Point", (500, 2000), (1.2, 2.4)),
]

telecom_contracts = []
circuits_rows = []
circuit_seq = 0
renewal_buckets_cycle = ["30d", "60d", "90d", "normal", "normal", "normal"]

for i in range(10):
    vendor = TELECOM_VENDORS[i]
    bucket = renewal_buckets_cycle[i % len(renewal_buckets_cycle)]
    n_circuits = random.randint(5, 11)
    circuit_specs = []
    total_monthly = 0.0
    for _ in range(n_circuits):
        tier_label, bw_range, rate_range = random.choice(CIRCUIT_TIERS)
        bandwidth = random.randint(*bw_range)
        rate = random.uniform(*rate_range)
        # ~8% of circuits are negotiated above benchmark (waste candidate)
        if random.random() < 0.08:
            rate *= random.uniform(1.25, 1.6)
        monthly = round(bandwidth * rate, 2)
        util = random.randint(30, 96)
        if random.random() < 0.08:
            util = random.randint(4, 22)  # seeded underutilization
        circuit_specs.append((tier_label, bandwidth, monthly, util))
        total_monthly += monthly

    contract = make_contract(vendor, "Network Circuit Services", total_monthly, term_years=random.choice([2, 3, 4]),
                              renewal_bucket=bucket, minimum_commitment=f"{n_circuits} active circuits")
    telecom_contracts.append(contract)

    for tier_label, bandwidth, monthly, util in circuit_specs:
        circuit_seq += 1
        circuits_rows.append({
            "circuit_id": f"CIRC-{circuit_seq:04d}",
            "contract_id": contract.contract_id,
            "vendor": vendor,
            "circuit_type": tier_label,
            "bandwidth_mbps": bandwidth,
            "site": f"{contract.region} Site {random.randint(1, 9)}",
            "region": contract.region,
            "monthly_cost": monthly,
            "utilization_pct": util,
            "install_date": rand_date(contract.start_date, min(contract.start_date + timedelta(days=200), TODAY)).isoformat(),
            "owner": owner_or_blank(0.15),
            "sla_tier": random.choice(["Gold", "Silver", "Bronze"]),
        })

CONTRACTS.extend(telecom_contracts)

# ---------------------------------------------------------------------------
# 2. Colocation contracts + colo line items
# ---------------------------------------------------------------------------

colo_contracts = []
colo_rows = []
colo_seq = 0

for i in range(6):
    vendor = COLO_VENDORS[i]
    n_items = random.randint(4, 9)
    line_items = []
    total_monthly = 0.0
    for _ in range(n_items):
        if random.random() < 0.5:
            # small retail rack deployment: $100-280 / U / month (Tier III retail band)
            rack_units = random.choice([4, 8, 12, 20, 42])
            rate_per_u = random.uniform(100, 280)
            if random.random() < 0.07:
                rate_per_u *= random.uniform(1.2, 1.5)
            monthly = round(rack_units * rate_per_u, 2)
            power_kw = round(rack_units * random.uniform(0.6, 1.1), 1)
            capacity_desc = f"{rack_units}U cabinet"
        else:
            # larger wholesale power-based cage: ~$196/kW at 250-500kW scale, prorated for smaller cages here
            power_kw = random.choice([15, 25, 40, 60])
            rate_per_kw = random.uniform(160, 230)
            if random.random() < 0.07:
                rate_per_kw *= random.uniform(1.2, 1.4)
            monthly = round(power_kw * rate_per_kw, 2)
            rack_units = random.choice([10, 20, 30])
            capacity_desc = f"{power_kw}kW private cage"

        cross_connects = random.randint(0, 6)
        remote_hands = random.choice([0, 0, 2, 4, 8])
        utilization = random.randint(35, 95)
        if random.random() < 0.08:
            utilization = random.randint(10, 24)
        line_items.append((capacity_desc, rack_units, power_kw, cross_connects, remote_hands, monthly, utilization))
        total_monthly += monthly

    contract = make_contract(vendor, "Colocation", total_monthly, term_years=random.choice([3, 4, 5]),
                              minimum_commitment=f"{n_items} facility deployment(s)")
    colo_contracts.append(contract)

    for capacity_desc, rack_units, power_kw, cross_connects, remote_hands, monthly, utilization in line_items:
        colo_seq += 1
        colo_rows.append({
            "colo_id": f"COLO-{colo_seq:04d}",
            "contract_id": contract.contract_id,
            "vendor": vendor,
            "site": f"{contract.region} DC{random.randint(1, 4)}",
            "capacity": capacity_desc,
            "rack_units": rack_units,
            "power_kw": power_kw,
            "cross_connects": cross_connects,
            "remote_hands_hours_monthly": remote_hands,
            "monthly_cost": monthly,
            "utilization_pct": utilization,
            "owner": owner_or_blank(0.15),
        })

CONTRACTS.extend(colo_contracts)

# ---------------------------------------------------------------------------
# 3. SaaS / license contracts
# ---------------------------------------------------------------------------

LICENSE_PRICE_BANDS = {
    # category: (unit_cost_lo, unit_cost_hi, pricing_model, seat_count_lo, seat_count_hi)
    "Identity & Access": (8, 15, "per_seat", 500, 2600),
    "Productivity Suite": (12, 22, "per_seat", 500, 2600),
    "Security - Endpoint": (6, 14, "per_seat", 500, 2600),
    "Observability": (20, 45, "per_seat", 60, 320),
    "DevOps Platform": (18, 38, "per_seat", 60, 320),
    "CRM / ERP": (60, 150, "per_seat", 60, 380),
    "HR / Finance": (15, 35, "per_seat", 30, 190),
    "AI / LLM Assistant": (25, 60, "consumption", 150, 1500),
}

license_contracts = []
license_rows = []
license_seq = 0

for category, vendors in SAAS_VENDORS.items():
    lo, hi, pricing_model, seat_lo, seat_hi = LICENSE_PRICE_BANDS[category]
    for vendor in vendors:
        n_products = 1 if random.random() < 0.45 else random.randint(2, 3)
        product_specs = []
        total_monthly = 0.0
        for p in range(n_products):
            purchased = random.randint(seat_lo, seat_hi)
            active_ratio = random.uniform(0.62, 0.99)
            if random.random() < 0.12:
                active_ratio = random.uniform(0.28, 0.56)  # seeded underutilization
            active_users = max(1, int(purchased * active_ratio))
            unit_cost = random.uniform(lo, hi)
            if random.random() < 0.08:
                unit_cost *= random.uniform(1.2, 1.5)  # above benchmark
            monthly = round(purchased * unit_cost, 2)
            product_name = f"{vendor} {['Core', 'Plus', 'Enterprise', 'Pro'][p % 4]}"
            product_specs.append((product_name, category, pricing_model, purchased, active_users, round(unit_cost, 2), monthly))
            total_monthly += monthly

        contract = make_contract(vendor, "Software License", total_monthly, term_years=random.choice([1, 2, 3]),
                                  minimum_commitment=f"{product_specs[0][3]} seats minimum" if pricing_model == "per_seat"
                                  else f"{product_specs[0][3]} committed seats (consumption true-up quarterly)")
        license_contracts.append(contract)

        for product_name, cat, pricing_model, purchased, active_users, unit_cost, monthly in product_specs:
            license_seq += 1
            license_rows.append({
                "license_id": f"LIC-{license_seq:04d}",
                "contract_id": contract.contract_id,
                "vendor": vendor,
                "product_name": product_name,
                "category": cat,
                "pricing_model": pricing_model,
                "purchased_count": purchased,
                "active_users": active_users,
                "unit_monthly_cost": unit_cost,
                "monthly_cost": monthly,
                "owner": owner_or_blank(0.15),
            })

CONTRACTS.extend(license_contracts)

# ---------------------------------------------------------------------------
# 4. Mobile / enterprise mobility contracts
# ---------------------------------------------------------------------------

MOBILE_TIERS = {
    "Basic": (30, 40),
    "Standard": (45, 60),
    "Premium": (65, 90),
}
DEPARTMENTS = ["Sales", "Field Services", "Engineering", "Operations", "Executive", "Support", "Logistics"]

mobile_contracts = []
mobile_rows = []
mobile_seq = 0

for vendor in MOBILE_VENDORS:
    n_lines = random.randint(20, 40)
    line_specs = []
    total_monthly = 0.0
    for _ in range(n_lines):
        tier = random.choices(["Basic", "Standard", "Premium"], weights=[0.35, 0.45, 0.2])[0]
        lo, hi = MOBILE_TIERS[tier]
        cost = random.uniform(lo, hi)
        if random.random() < 0.06:
            cost *= random.uniform(1.15, 1.4)
        assigned = "" if random.random() < 0.05 else f"{random.choice(OWNERS)}"
        last_activity = random.randint(0, 45)
        if random.random() < 0.06:
            last_activity = random.randint(95, 260)  # seeded inactive line
        line_specs.append((tier, round(cost, 2), assigned, last_activity))
        total_monthly += cost

    contract = make_contract(vendor, "Mobile Services", total_monthly, term_years=random.choice([2, 3]),
                              minimum_commitment=f"{n_lines} active lines")
    mobile_contracts.append(contract)

    for tier, cost, assigned, last_activity in line_specs:
        mobile_seq += 1
        mobile_rows.append({
            "line_id": f"MBL-{mobile_seq:04d}",
            "contract_id": contract.contract_id,
            "vendor": vendor,
            "plan_tier": tier,
            "monthly_cost": cost,
            "assigned_user": assigned,
            "department": random.choice(DEPARTMENTS),
            "last_activity_days": last_activity,
            "owner": owner_or_blank(0.15),
        })

CONTRACTS.extend(mobile_contracts)

# ---------------------------------------------------------------------------
# 5. Unified Communications + standalone support/DR/MDR contracts
#    (monolithic contracts with no granular child-asset breakdown - realistic)
# ---------------------------------------------------------------------------

for vendor in UC_VENDORS:
    seats = random.randint(400, 2200)
    unit = random.uniform(9, 18)
    monthly = round(seats * unit, 2)
    contract = make_contract(vendor, "Unified Communications", monthly, term_years=random.choice([2, 3]),
                              minimum_commitment=f"{seats} UC seats")
    CONTRACTS.append(contract)

for vendor in SUPPORT_VENDORS:
    monthly = random.uniform(8000, 42000)
    service_type = random.choice(["Managed Support", "Managed Detection & Response", "Disaster Recovery"])
    contract = make_contract(vendor, service_type, monthly, term_years=random.choice([1, 2, 3]),
                              minimum_commitment="Tiered SLA response commitment")
    CONTRACTS.append(contract)

# ---------------------------------------------------------------------------
# Benchmark rates
# ---------------------------------------------------------------------------

BENCHMARK_ROWS = [
    {"category": "circuit_DIA-100", "benchmark_rate": 4.2, "unit": "usd_per_mbps_month"},
    {"category": "circuit_DIA-500", "benchmark_rate": 2.4, "unit": "usd_per_mbps_month"},
    {"category": "circuit_DIA-1000", "benchmark_rate": 1.35, "unit": "usd_per_mbps_month"},
    {"category": "circuit_MPLS-Backbone", "benchmark_rate": 0.48, "unit": "usd_per_mbps_month"},
    {"category": "circuit_Point-to-Point", "benchmark_rate": 1.7, "unit": "usd_per_mbps_month"},
    {"category": "colo_rack_unit", "benchmark_rate": 190, "unit": "usd_per_u_month"},
    {"category": "colo_power_kw", "benchmark_rate": 196, "unit": "usd_per_kw_month"},
    {"category": "mobile_Basic", "benchmark_rate": 35, "unit": "usd_per_line_month"},
    {"category": "mobile_Standard", "benchmark_rate": 52, "unit": "usd_per_line_month"},
    {"category": "mobile_Premium", "benchmark_rate": 76, "unit": "usd_per_line_month"},
    {"category": "license_Identity & Access", "benchmark_rate": 11, "unit": "usd_per_seat_month"},
    {"category": "license_Productivity Suite", "benchmark_rate": 16, "unit": "usd_per_seat_month"},
    {"category": "license_Security - Endpoint", "benchmark_rate": 9, "unit": "usd_per_seat_month"},
    {"category": "license_Observability", "benchmark_rate": 30, "unit": "usd_per_seat_month"},
    {"category": "license_DevOps Platform", "benchmark_rate": 26, "unit": "usd_per_seat_month"},
    {"category": "license_CRM / ERP", "benchmark_rate": 95, "unit": "usd_per_seat_month"},
    {"category": "license_HR / Finance", "benchmark_rate": 23, "unit": "usd_per_seat_month"},
    {"category": "license_AI / LLM Assistant", "benchmark_rate": 38, "unit": "usd_per_seat_month"},
]

# ---------------------------------------------------------------------------
# 6. Realistic full-length contract prose (for the LLM extraction agent)
# ---------------------------------------------------------------------------

SLA_CREDIT_CLAUSES = [
    "Service Level Credits: Vendor shall issue a service credit equal to 5% of the "
    "affected month's fees for each full hour of Service unavailability beyond the "
    "committed uptime SLA of 99.9%, capped at 30% of monthly fees in any calendar month.",
    "Service Level Credits: In the event measured availability falls below 99.95% in a "
    "calendar month, Customer shall receive a credit of 2% of that month's fees per "
    "0.1% shortfall, capped at 25% of monthly fees.",
]

MFN_CLAUSES = [
    "Most Favored Pricing: Vendor represents that the pricing herein is no less favorable "
    "than pricing offered to similarly situated customers of comparable volume. Should "
    "Vendor extend more favorable pricing to a similarly situated customer during the Term, "
    "Vendor shall extend equivalent terms to Customer upon written request.",
]

PRICE_PROTECTION_CLAUSES = [
    "Price Protection: Unit pricing shall not increase during the initial Term. Any "
    "renewal term pricing adjustment is limited to the Annual Escalator set forth above, "
    "provided Customer maintains the Minimum Commitment.",
]

LIABILITY_CLAUSES = [
    "Limitation of Liability: Except for breaches of confidentiality or indemnification "
    "obligations, each party's aggregate liability arising out of this Agreement shall not "
    "exceed the fees paid or payable in the twelve (12) months preceding the claim.",
]

DPA_CLAUSES = [
    "Data Processing: The parties' Data Processing Addendum, incorporated by reference, "
    "governs the processing of Customer Data, including applicable cross-border transfer "
    "mechanisms and breach notification timelines.",
]

CATEGORY_INTROS = {
    "Network Circuit Services": (
        "This Master Service Agreement ('Agreement') governs the provisioning of dedicated "
        "network circuit services, including {commitment}, delivered by Vendor to Customer's "
        "designated sites in the {region} region."
    ),
    "Colocation": (
        "This Colocation Services Agreement ('Agreement') governs Customer's use of data "
        "center space, power, and cross-connect services at Vendor's facility, covering "
        "{commitment}."
    ),
    "Software License": (
        "This Software Subscription Agreement ('Agreement') governs Customer's subscription "
        "to Vendor's software products on a {commitment} basis."
    ),
    "Mobile Services": (
        "This Enterprise Mobility Services Agreement ('Agreement') governs wireless voice and "
        "data service for Customer's workforce, covering {commitment}."
    ),
    "Unified Communications": (
        "This Unified Communications Services Agreement ('Agreement') governs cloud voice, "
        "messaging, and conferencing services covering {commitment}."
    ),
    "Managed Support": (
        "This Managed Services Agreement ('Agreement') governs ongoing infrastructure support "
        "services, covering {commitment}."
    ),
    "Managed Detection & Response": (
        "This Managed Detection & Response Services Agreement ('Agreement') governs 24x7 "
        "security monitoring and incident response services, covering {commitment}."
    ),
    "Disaster Recovery": (
        "This Disaster Recovery Services Agreement ('Agreement') governs failover "
        "infrastructure and recovery services, covering {commitment}."
    ),
}


def render_contract_doc(contract: Contract, extra_clauses: list[str]) -> str:
    intro_template = CATEGORY_INTROS.get(
        contract.service_type,
        "This Master Service Agreement ('Agreement') governs the services described herein, "
        "covering {commitment}.",
    )
    intro = intro_template.format(commitment=contract.minimum_commitment or "the services described below",
                                   region=contract.region)

    lines = []
    lines.append(f"CONTRACT ID: {contract.contract_id}")
    lines.append(f"VENDOR: {contract.vendor}")
    lines.append(f"CATEGORY: {contract.service_type}")
    lines.append("")
    lines.append(intro)
    lines.append("")
    lines.append(
        f"1. TERM AND RENEWAL. This Agreement commences on {contract.start_date.isoformat()} and "
        f"continues through {contract.end_date.isoformat()} (the 'Term'), unless earlier terminated as "
        f"provided herein. "
        + (
            f"This Agreement shall automatically renew for successive one-year terms unless either "
            f"party provides written notice of non-renewal at least {contract.notice_days} days prior to "
            f"the end of the then-current Term."
            if contract.auto_renew == "Yes"
            else f"This Agreement shall terminate at the end of the Term unless renewed by mutual written "
            f"agreement of the parties at least {contract.notice_days} days prior to expiration."
        )
    )
    lines.append("")
    lines.append(
        f"2. FEES. Customer shall pay Vendor recurring fees of ${contract.monthly_cost:,.2f} per month "
        f"(${contract.annual_cost:,.2f} annualized), subject to an Annual Escalator of "
        f"{contract.escalation_pct}% applied on each anniversary of the Effective Date."
    )
    lines.append("")
    lines.append(
        f"3. TERMINATION. Either party may terminate this Agreement for uncured material breach upon "
        f"thirty (30) days' written notice. If Customer terminates for convenience prior to the end of "
        f"the Term, Customer shall pay an early termination fee equal to {contract.termination_fee_pct}% "
        f"of the remaining committed charges under the Term."
    )
    lines.append("")

    section_num = 4
    for clause in extra_clauses:
        lines.append(f"{section_num}. {clause}")
        lines.append("")
        section_num += 1

    lines.append(
        f"{section_num}. GOVERNING LAW. This Agreement is governed by the laws of the state in which "
        f"Customer's {contract.region} headquarters is located, without regard to conflict of law "
        f"principles."
    )
    return "\n".join(lines)


def select_doc_contracts() -> list[Contract]:
    picks: list[Contract] = []
    picks += random.sample(telecom_contracts, 3)
    picks += random.sample(colo_contracts, 2)
    ai_llm = [c for c in license_contracts if "Nimbus" in c.vendor or "CogniStack" in c.vendor or "Synapse" in c.vendor]
    non_ai_license = [c for c in license_contracts if c not in ai_llm]
    picks += random.sample(ai_llm, min(2, len(ai_llm)))
    picks += random.sample(non_ai_license, 3)
    picks += random.sample(mobile_contracts, 2)
    picks += [c for c in CONTRACTS if c.service_type == "Unified Communications"][:1]
    picks += [c for c in CONTRACTS if c.service_type in
              ("Managed Support", "Managed Detection & Response", "Disaster Recovery")][:2]
    return picks


def write_contract_docs() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in DOCS_DIR.glob("*.txt"):
        stale.unlink()
    count = 0
    for contract in select_doc_contracts():
        extra_clauses = [random.choice(SLA_CREDIT_CLAUSES), random.choice(LIABILITY_CLAUSES)]
        if random.random() < 0.4:
            extra_clauses.append(random.choice(MFN_CLAUSES))
        if random.random() < 0.4:
            extra_clauses.append(random.choice(PRICE_PROTECTION_CLAUSES))
        extra_clauses.append(random.choice(DPA_CLAUSES))

        doc_text = render_contract_doc(contract, extra_clauses)
        out_path = DOCS_DIR / f"{contract.contract_id}.txt"
        out_path.write_text(doc_text, encoding="utf-8")
        count += 1
    return count


# ---------------------------------------------------------------------------
# Write CSVs
# ---------------------------------------------------------------------------


def write_csv(path: Path, header_comment: list[str], fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        for line in header_comment:
            fh.write(f"# {line}\n")
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    contract_rows = [
        {
            "contract_id": c.contract_id,
            "vendor": c.vendor,
            "service_type": c.service_type,
            "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat(),
            "annual_cost": c.annual_cost,
            "monthly_cost": c.monthly_cost,
            "auto_renew": c.auto_renew,
            "notice_days": c.notice_days,
            "termination_fee_pct": c.termination_fee_pct,
            "escalation_pct": c.escalation_pct,
            "owner": c.owner,
            "status": c.status,
            "region": c.region,
            "minimum_commitment": c.minimum_commitment,
        }
        for c in CONTRACTS
    ]

    write_csv(
        SEED_DIR / "contracts.csv",
        ["Synthetic master contract inventory for PACT (fictional vendors, research-grounded pricing).",
         "Generated by app/data/generate_seed_data.py - do not hand-edit without regenerating."],
        ["contract_id", "vendor", "service_type", "start_date", "end_date", "annual_cost", "monthly_cost",
         "auto_renew", "notice_days", "termination_fee_pct", "escalation_pct", "owner", "status", "region",
         "minimum_commitment"],
        contract_rows,
    )

    write_csv(SEED_DIR / "circuits.csv",
              ["Synthetic telecom circuit inventory referencing contracts.csv via contract_id."],
              ["circuit_id", "contract_id", "vendor", "circuit_type", "bandwidth_mbps", "site", "region",
               "monthly_cost", "utilization_pct", "install_date", "owner", "sla_tier"],
              circuits_rows)

    write_csv(SEED_DIR / "colo_contracts.csv",
              ["Synthetic colocation deployment inventory referencing contracts.csv via contract_id."],
              ["colo_id", "contract_id", "vendor", "site", "capacity", "rack_units", "power_kw",
               "cross_connects", "remote_hands_hours_monthly", "monthly_cost", "utilization_pct", "owner"],
              colo_rows)

    write_csv(SEED_DIR / "licenses.csv",
              ["Synthetic SaaS/software license inventory referencing contracts.csv via contract_id.",
               "pricing_model is 'per_seat' or 'consumption' (committed-seat, usage-true-up)."],
              ["license_id", "contract_id", "vendor", "product_name", "category", "pricing_model",
               "purchased_count", "active_users", "unit_monthly_cost", "monthly_cost", "owner"],
              license_rows)

    write_csv(SEED_DIR / "mobile_lines.csv",
              ["Synthetic enterprise mobility line inventory referencing contracts.csv via contract_id."],
              ["line_id", "contract_id", "vendor", "plan_tier", "monthly_cost", "assigned_user", "department",
               "last_activity_days", "owner"],
              mobile_rows)

    write_csv(SEED_DIR / "benchmark_rates.csv",
              ["Market benchmark reference rates used by the waste/benchmark agents.",
               "Grounded in 2026 colocation/telecom/SaaS pricing research; see docs/architecture.md."],
              ["category", "benchmark_rate", "unit"],
              BENCHMARK_ROWS)

    print(f"Contracts: {len(contract_rows)}")
    print(f"Circuits: {len(circuits_rows)}")
    print(f"Colo line items: {len(colo_rows)}")
    print(f"Licenses: {len(license_rows)}")
    print(f"Mobile lines: {len(mobile_rows)}")
    total_annual = sum(c.annual_cost for c in CONTRACTS)
    print(f"Total annual spend: ${total_annual:,.0f}")

    doc_count = write_contract_docs()
    print(f"Contract documents written: {doc_count}")


if __name__ == "__main__":
    main()
