// rescue.rs — Rescue feature scaffolding (CP7)
// Full logic implemented in CP8/CP9. This file provides the data types only.

#[derive(Debug, Clone, PartialEq)]
pub enum RescueLeg {
    Short,
    Long,
}

#[derive(Debug, Clone)]
pub struct RescueState {
    pub in_rescue: bool,
    pub leg: RescueLeg,
    pub anchor_price: f64,
    pub flip_count: usize,
    pub breakeven_target_pct: f64,
}

impl Default for RescueState {
    fn default() -> Self {
        RescueState {
            in_rescue: false,
            leg: RescueLeg::Short,
            anchor_price: 0.0,
            flip_count: 0,
            breakeven_target_pct: 0.0,
        }
    }
}
