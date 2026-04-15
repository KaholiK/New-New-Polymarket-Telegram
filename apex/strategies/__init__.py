"""All strategies + dynamic registry keyed by config toggles."""

from __future__ import annotations

from apex.config import get_settings
from apex.strategies.base import BaseStrategy, DataContext
from apex.strategies.book_divergence import BookDivergenceStrategy
from apex.strategies.complement_arb import ComplementArbStrategy
from apex.strategies.contrarian import ContrarianStrategy
from apex.strategies.fair_value import FairValueStrategy
from apex.strategies.injury_reprice import InjuryRepriceStrategy
from apex.strategies.momentum_confirmation import MomentumConfirmationStrategy
from apex.strategies.news_shock import NewsShockStrategy
from apex.strategies.orderbook_scalp import OrderbookScalpStrategy
from apex.strategies.prelock_reprice import PrelockRepriceStrategy
from apex.strategies.sharp_follow import SharpFollowStrategy
from apex.strategies.steam_move import SteamMoveStrategy

ALL_STRATEGY_CLASSES: list[type[BaseStrategy]] = [
    FairValueStrategy,
    BookDivergenceStrategy,
    NewsShockStrategy,
    InjuryRepriceStrategy,
    SteamMoveStrategy,
    ContrarianStrategy,
    OrderbookScalpStrategy,
    PrelockRepriceStrategy,
    ComplementArbStrategy,
    SharpFollowStrategy,
    MomentumConfirmationStrategy,
]


def enabled_strategies() -> list[BaseStrategy]:
    """Instantiate strategies turned on in config."""
    s = get_settings()
    flags = {
        "fair_value": s.strategy_fair_value,
        "book_divergence": s.strategy_book_divergence,
        "news_shock": s.strategy_news_shock,
        "injury_reprice": s.strategy_injury_reprice,
        "steam_move": s.strategy_steam_move,
        "contrarian": s.strategy_contrarian,
        "orderbook_scalp": s.strategy_orderbook_scalp,
        "prelock_reprice": s.strategy_prelock_reprice,
        "complement_arb": s.strategy_complement_arb,
        "sharp_follow": s.strategy_sharp_follow,
        "momentum_confirmation": s.strategy_momentum,
    }
    out: list[BaseStrategy] = []
    for cls in ALL_STRATEGY_CLASSES:
        inst = cls()
        if flags.get(inst.name, True):
            out.append(inst)
    return out


__all__ = [
    "ALL_STRATEGY_CLASSES",
    "BaseStrategy",
    "DataContext",
    "enabled_strategies",
]
