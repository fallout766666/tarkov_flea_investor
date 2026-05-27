import math

T_I = 0.03
T_R = 0.03


def flea_listing_fee(
    base_price: int,
    list_price: int,
    quantity: int = 1,
    *,
    intel_center_level: int = 0,
    hideout_management_skill: int = 0,
) -> int:
    """EFT flea market listing fee.

    Formula:  VO * Ti * 4^PO * Q  +  VR * Tr * 4^PR * Q
        VO = base_price        (per item, assuming "Require for all" is off)
        VR = list_price        (per item, in roubles for cash listings)
        PO = log10(VO / VR), raised to ^1.08 if VR < VO  (underprice penalty)
        PR = log10(VR / VO), raised to ^1.08 if VR >= VO (overprice penalty)
        Q  = quantity
        Ti = Tr = 0.03

    Discount: -30% if Intelligence Center is level 3, plus 0.3% per
    Hideout Management skill level (capped at 50 → max 45% off combined).
    """
    if base_price <= 0 or list_price <= 0 or quantity <= 0:
        return 0

    p_o = math.log10(base_price / list_price)
    p_r = math.log10(list_price / base_price)

    if list_price < base_price:
        p_o = p_o**1.08
    if list_price >= base_price:
        p_r = p_r**1.08

    fee = (
        base_price * T_I * (4**p_o) * quantity
        + list_price * T_R * (4**p_r) * quantity
    )

    if intel_center_level >= 3:
        skill = max(0, min(hideout_management_skill, 50))
        discount = 0.30 + skill * 0.003
        fee *= 1 - discount

    return round(fee)


def flea_net_proceeds(
    base_price: int,
    list_price: int,
    quantity: int = 1,
    *,
    intel_center_level: int = 0,
    hideout_management_skill: int = 0,
) -> int:
    """Roubles received after the flea market deducts its listing fee."""
    fee = flea_listing_fee(
        base_price,
        list_price,
        quantity,
        intel_center_level=intel_center_level,
        hideout_management_skill=hideout_management_skill,
    )
    return list_price * quantity - fee
