"""
AlphaX POS — Unified Boot

The cashier SPA calls `pos_boot(terminal)` exactly once on login. The response
contains everything needed to run the terminal offline-capable for a shift:

    - terminal       : Terminal record (basic identity)
    - outlet         : Outlet record (company, branch, warehouse, price list, ...)
    - domains        : Active domain packs with their capability flags
    - profile        : POS Profile (modes of payment, item groups, tax template)
    - theme          : Theme record if linked
    - loyalty        : Active programs scoped to this outlet's domains
    - payment_methods: Modes of payment + terminal-capture flags
    - scale_rules    : Weighing-scale barcode rules (prefix-based)
    - taxes          : Sales taxes & charges template (rows)
    - currency       : Default currency + symbol + precision
    - server_time    : Server clock (for offline-skew detection)
    - features       : Union of feature flags from active domains

Performance: this is one query-heavy call, but it's ONLY called on login
and on shift open. Caching at frappe.cache layer (per-terminal, 5 min TTL)
makes it cheap on subsequent logins.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


_FEATURE_FIELDS = [
    "uses_floor_plan",
    "uses_kds",
    "uses_modifiers",
    "uses_recipes",
    "uses_scale",
    "uses_batch_expiry",
    "uses_serial",
    "uses_appointments",
    "uses_tips",
    "uses_service_charge",
    "uses_courses",
    "uses_table_qr",
    "uses_split_bill",
    "uses_loyalty",
    "uses_prescription",
]


def _resolve_outlet_for_terminal(terminal_doc):
    """A Terminal can be linked to an Outlet directly, or via its POS Profile."""
    outlet_name = getattr(terminal_doc, "outlet", None)
    if outlet_name and frappe.db.exists("AlphaX POS Outlet", outlet_name):
        return outlet_name

    profile_name = getattr(terminal_doc, "pos_profile", None)
    if profile_name:
        outlet = frappe.db.get_value(
            "AlphaX POS Profile", profile_name, "alphax_outlet"
        )
        if outlet and frappe.db.exists("AlphaX POS Outlet", outlet):
            return outlet
    return None


def _domain_pack_summary(domain_code):
    """Return the pack's capability dict, or None if pack missing."""
    if not domain_code:
        return None
    if not frappe.db.exists("AlphaX POS Domain Pack", domain_code):
        return None
    pack = frappe.db.get_value(
        "AlphaX POS Domain Pack",
        domain_code,
        ["domain_code", "label", "icon", "enabled", "default_item_group"]
        + _FEATURE_FIELDS,
        as_dict=True,
    )
    return pack


def _collect_active_domains(outlet_doc):
    """Return list of domain pack summaries for this outlet (in order)."""
    out = []
    seen = set()
    for row in (outlet_doc.domains or []):
        code = row.domain
        if not code or code in seen:
            continue
        seen.add(code)
        summary = _domain_pack_summary(code)
        if summary and summary.get("enabled"):
            out.append(summary)

    if not out:
        legacy = (outlet_doc.pos_type or "").strip()
        if legacy and legacy not in ("Use Global", ""):
            summary = _domain_pack_summary(legacy)
            if summary:
                out.append(summary)

    if not out:
        fallback = _domain_pack_summary("Generic")
        if fallback:
            out.append(fallback)

    return out


def _union_features(domains):
    """Take the OR of every feature flag across active domains."""
    feats = {f: 0 for f in _FEATURE_FIELDS}
    for d in domains:
        for f in _FEATURE_FIELDS:
            if d.get(f):
                feats[f] = 1
    return feats


def _loyalty_programs_for_outlet(outlet_doc, active_domain_codes):
    """All enabled loyalty programs that apply to this outlet."""
    rows = frappe.get_all(
        "AlphaX POS Loyalty Program",
        filters={"enabled": 1, "company": outlet_doc.company},
        fields=[
            "name",
            "program_code",
            "program_name",
            "domain_scope",
            "earn_basis",
            "default_earn_points",
            "default_earn_per_amount",
            "redemption_value",
            "min_points_to_redeem",
            "max_redeem_percent",
            "expiry_days",
        ],
    )
    out = []
    for r in rows:
        scope = r.get("domain_scope") or "All Domains"
        if scope == "All Domains" or scope in active_domain_codes:
            out.append(r)
    return out


def _payment_methods_for_profile(profile_name):
    if not profile_name:
        return []
    rows = frappe.get_all(
        "AlphaX POS Profile Payment Method",
        filters={"parent": profile_name},
        fields=[
            "mode_of_payment",
            "default",
            "amount",
            "allow_in_returns",
        ],
        order_by="idx asc",
    )
    enriched = []
    for r in rows:
        if not r.get("mode_of_payment"):
            continue
        mop = frappe.db.get_value(
            "Mode of Payment",
            r["mode_of_payment"],
            [
                "type",
                "alphax_capture_terminal_data",
                "alphax_terminal_settings",
                "alphax_require_terminal_approval",
                "alphax_allow_manual_ref",
            ],
            as_dict=True,
        ) or {}
        enriched.append({**r, **mop})
    return enriched


def _scale_rules():
    rules = frappe.get_all(
        "AlphaX POS Scale Barcode Rule",
        filters={},
        fields=[
            "name",
            "prefix",
            "total_length",
            "code_start",
            "code_length",
            "value_start",
            "value_length",
            "value_kind",
            "value_divisor",
            "check_digit_present",
        ],
        order_by="prefix",
    )
    return rules


def _taxes_rows(template):
    if not template:
        return []
    return frappe.get_all(
        "Sales Taxes and Charges",
        filters={"parent": template},
        fields=[
            "charge_type",
            "account_head",
            "rate",
            "tax_amount",
            "description",
            "included_in_print_rate",
            "cost_center",
        ],
        order_by="idx asc",
    )


def _company_currency(company):
    if not company:
        return {"currency": "USD", "symbol": "$", "precision": 2}
    cur = frappe.db.get_value("Company", company, "default_currency")
    cur_doc = frappe.db.get_value(
        "Currency", cur, ["symbol", "smallest_currency_fraction_value"], as_dict=True
    ) or {}
    return {
        "currency": cur,
        "symbol": cur_doc.get("symbol") or cur,
        "precision": 2,
    }


@frappe.whitelist()
def pos_boot(terminal):
    """One call returns the entire bootstrap payload."""
    if not terminal or not frappe.db.exists("AlphaX POS Terminal", terminal):
        frappe.throw(_("Terminal not found: {0}").format(terminal))

    cache_key = f"alphax_pos_boot::{terminal}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        cached["server_time"] = now_datetime().isoformat()
        cached["from_cache"] = True
        return cached

    t = frappe.get_doc("AlphaX POS Terminal", terminal)
    outlet_name = _resolve_outlet_for_terminal(t)

    payload = {
        "terminal": {
            "name": t.name,
            "terminal_name": getattr(t, "terminal_name", t.name),
            "pos_profile": getattr(t, "pos_profile", None),
            "outlet": outlet_name,
        },
        "outlet": None,
        "domains": [],
        "features": {f: 0 for f in _FEATURE_FIELDS},
        "profile": None,
        "theme": None,
        "loyalty_programs": [],
        "payment_methods": [],
        "scale_rules": [],
        "taxes": [],
        "currency": {"currency": "USD", "symbol": "$", "precision": 2},
        "server_time": now_datetime().isoformat(),
        "from_cache": False,
    }

    if outlet_name:
        outlet = frappe.get_doc("AlphaX POS Outlet", outlet_name)
        domains = _collect_active_domains(outlet)
        active_codes = [d["domain_code"] for d in domains]
        payload["outlet"] = {
            "name": outlet.name,
            "outlet_name": outlet.outlet_name,
            "company": outlet.company,
            "branch": outlet.branch,
            "warehouse": outlet.warehouse,
            "cost_center": outlet.cost_center,
            "primary_domain": outlet.primary_domain,
            "update_stock": int(outlet.update_stock or 0),
            "default_price_list": outlet.default_price_list,
            "default_loyalty_program": outlet.default_loyalty_program,
            "service_charge_item": outlet.service_charge_item,
            "tips_item": outlet.tips_item,
            "sales_taxes_and_charges_template": outlet.sales_taxes_and_charges_template,
        }
        payload["domains"] = domains
        payload["features"] = _union_features(domains)
        payload["loyalty_programs"] = _loyalty_programs_for_outlet(outlet, active_codes)
        payload["taxes"] = _taxes_rows(outlet.sales_taxes_and_charges_template)
        payload["currency"] = _company_currency(outlet.company)

    profile_name = getattr(t, "pos_profile", None)
    if profile_name and frappe.db.exists("AlphaX POS Profile", profile_name):
        prof = frappe.get_doc("AlphaX POS Profile", profile_name)
        payload["profile"] = {
            "name": prof.name,
            "currency": getattr(prof, "currency", None),
            "language": getattr(prof, "language", None),
            "theme": getattr(prof, "theme", None),
        }
        payload["payment_methods"] = _payment_methods_for_profile(profile_name)
        theme_name = getattr(prof, "theme", None)
        if theme_name and frappe.db.exists("AlphaX POS Theme", theme_name):
            theme = frappe.get_doc("AlphaX POS Theme", theme_name)
            payload["theme"] = theme.as_dict()

    payload["scale_rules"] = _scale_rules()

    frappe.cache().set_value(cache_key, payload, expires_in_sec=300)
    return payload


@frappe.whitelist()
def invalidate_boot_cache(terminal=None):
    """Manager flips an outlet flag, calls this to refresh terminals."""
    if terminal:
        frappe.cache().delete_value(f"alphax_pos_boot::{terminal}")
    else:
        for key in frappe.cache().get_keys("alphax_pos_boot::*"):
            frappe.cache().delete_value(key)
    return {"ok": True}
