export const DEFAULTS = {
  platform_fee_rate: 0.13,
  avg_ship_cost: 15.0,
  cgc_grading_cost: 45.0,
  cgc_ship_insure_cost: 20.0,
  time_penalty_rate: 0.05,
  slab_lift_min_dollars: 150.0,
  slab_lift_min_pct: 0.2,
};

export function recommendChannel(marketPrice?: number | null, confidence?: string | null, isKey = false) {
  const p = marketPrice || 0;
  const c = (confidence || "").toLowerCase();
  if (p >= 2500 || (p >= 1200 && c === "high") || (isKey && p >= 900)) return "heritage_or_major_auction";
  if (p >= 250) return "ebay_fixed_price_offers";
  return "ebay_fixed_price_offers";
}

export function dynamicAskMultiplier(r: any) {
  const market = Number(r?.market_price || 0);
  const conf = String(r?.confidence || "").toLowerCase();
  const gradeClass = String(r?.grade_class || "");
  const activeCount = Number(r?.active_count || 0);

  let m = 1.05;
  if (gradeClass === "slabbed") m += 0.03;
  if (conf === "high") m += 0.02;
  else if (conf === "low") m -= 0.02;
  if (market >= 1000) m += 0.03;
  else if (market >= 300) m += 0.01;
  if (activeCount >= 8) m += 0.01;
  else if (activeCount === 0) m -= 0.01;
  return Math.max(1.03, Math.min(1.18, m));
}

export function decisionForRow(r: any, assumptions = DEFAULTS) {
  const market = r.market_price as number | null;
  const gradeClass = r.grade_class as string;
  const status = r.status as string;
  const grade = r.grade_numeric as number | null;
  const qualifiedFlag = r.qualified_flag || 0;

  if (status === "sold") return { action: "already_sold" };

  const targetMult = dynamicAskMultiplier(r);
  const activeAnchor = r.active_anchor_price as number | null;
  const anchorMult = (market || 0) >= 500 ? 1.3 : 1.2;
  const modelAnchor = market ? Number((market * anchorMult).toFixed(2)) : null;
  let anchorPrice = modelAnchor;
  if (activeAnchor != null && modelAnchor != null) anchorPrice = Number(Math.max(modelAnchor, activeAnchor).toFixed(2));
  else if (activeAnchor != null) anchorPrice = Number(activeAnchor.toFixed(2));

  if (gradeClass === "slabbed") {
    return {
      target_price: market ? Number((market * targetMult).toFixed(2)) : null,
      floor_price: market ? Number((market * (String(r.confidence || "") === "high" ? 0.92 : 0.88)).toFixed(2)) : null,
      anchor_price: anchorPrice,
      channel_hint: recommendChannel(market, r.confidence),
      action: "list_now_slabbed",
    };
  }

  if (market == null) {
    if (gradeClass === "raw_no_community") return { channel_hint: "prep_community_then_ebay", action: "get_community_grade" };
    return { channel_hint: "ebay_fixed_price_offers", action: "needs_comps" };
  }

  const netRaw = market * (1 - assumptions.platform_fee_rate) - assumptions.avg_ship_cost;
  const slabMult = grade && grade >= 8.5 ? 1.6 : grade && grade >= 7.0 ? 1.35 : 1.2;
  const expectedSlabGross = market * slabMult;
  const netSlabbed =
    expectedSlabGross * (1 - assumptions.platform_fee_rate) -
    assumptions.avg_ship_cost -
    assumptions.cgc_grading_cost -
    assumptions.cgc_ship_insure_cost -
    expectedSlabGross * assumptions.time_penalty_rate;
  const slabLift = netSlabbed - netRaw;
  const slabLiftPct = netRaw > 0 ? slabLift / netRaw : 0;

  let action = "sell_raw_now";
  if (slabLift >= assumptions.slab_lift_min_dollars && slabLiftPct >= assumptions.slab_lift_min_pct) action = "slab_candidate";
  else if (gradeClass === "raw_no_community") action = "get_community_grade";

  return {
    net_raw: Number(netRaw.toFixed(2)),
    net_slabbed: Number(netSlabbed.toFixed(2)),
    slab_lift: Number(slabLift.toFixed(2)),
    slab_lift_pct: Number((slabLiftPct * 100).toFixed(1)),
    anchor_price: anchorPrice,
    target_price: Number((market * targetMult).toFixed(2)),
    floor_price: Number((market * (String(r.confidence || "") === "high" ? 0.92 : 0.88)).toFixed(2)),
    channel_hint: recommendChannel(market, r.confidence),
    action,
  };
}
