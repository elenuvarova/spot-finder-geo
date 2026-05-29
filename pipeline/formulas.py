"""Per-type underserved-demand opportunity formulas.

A registry mapping each SpotFinder type to a function that computes the RAW
opportunity score for one H3 hex. The three formulas are intentionally
DISTINCT (different inputs per type) and must NOT be collapsed into one shared
weighted formula:

  cafe          destination / daytime traffic
                raw = (traffic_norm + 0.5*transit_norm) * income_norm
                      / (1 + comp_cafe)

  bakery        convenience, bought near home (traffic/offices NOT used)
                raw = residential_norm * gap_norm_bakery
                      * (0.5 + 0.5*income_norm) / (1 + comp_bakery)

  confectionery discretionary, light destination
                raw = income_norm * (0.6*traffic_norm + 0.4*residential_norm)
                      / (1 + comp_confectionery)

Each function takes a `row` (a mapping/Series with the *_norm drivers, the
per-type comp_<type> counts, and gap_norm_<type> for bakery) and returns a
float RAW score. compute.py turns RAW into the within-type percentile opp_<type>.
"""

import config


def cafe_formula(row):
    """Cafe: a daytime DESTINATION. Rewards passing traffic + transit access
    + spending power, penalised by existing cafe competition.

    Inputs used: traffic_norm, transit_norm, income_norm, comp_cafe.
    (Residential / gap deliberately NOT used: cafes are destinations, not
    home-convenience purchases.)
    """
    w = config.FORMULA_WEIGHTS["cafe"]
    traffic_norm = float(row["traffic_norm"])
    transit_norm = float(row["transit_norm"])
    income_norm = float(row["income_norm"])
    comp_cafe = float(row["comp_cafe"])

    numerator = (traffic_norm + w["transit_weight"] * transit_norm) * income_norm
    return numerator / (1.0 + comp_cafe)


def bakery_formula(row):
    """Bakery: a CONVENIENCE good bought near home. Rewards residents and an
    UNDERSERVED distance gap, lightly modulated by income, penalised by
    existing bakery competition.

    Inputs used: residential_norm, gap_norm_bakery, income_norm, comp_bakery.
    (Traffic / offices / transit deliberately NOT used.)
    """
    w = config.FORMULA_WEIGHTS["bakery"]
    residential_norm = float(row["residential_norm"])
    gap_norm = float(row["gap_norm_bakery"])
    income_norm = float(row["income_norm"])
    comp_bakery = float(row["comp_bakery"])

    income_factor = w["income_floor"] + w["income_span"] * income_norm
    numerator = residential_norm * gap_norm * income_factor
    return numerator / (1.0 + comp_bakery)


def confectionery_formula(row):
    """Confectionery: a DISCRETIONARY treat / light destination. Rewards
    spending power gated on a blend of passing traffic and nearby residents,
    penalised by existing confectionery competition.

    Inputs used: income_norm, traffic_norm, residential_norm, comp_confectionery.
    """
    w = config.FORMULA_WEIGHTS["confectionery"]
    income_norm = float(row["income_norm"])
    traffic_norm = float(row["traffic_norm"])
    residential_norm = float(row["residential_norm"])
    comp_conf = float(row["comp_confectionery"])

    blend = w["traffic_weight"] * traffic_norm + w["residential_weight"] * residential_norm
    numerator = income_norm * blend
    return numerator / (1.0 + comp_conf)


# Registry: type name -> raw-score function. compute.py iterates this so the
# three formulas stay distinct and independently testable.
FORMULA_REGISTRY = {
    "cafe": cafe_formula,
    "bakery": bakery_formula,
    "confectionery": confectionery_formula,
}
