"""Trading / screening knobs (paper trading — tune freely)."""

# Entry signal (aligned momentum — see monitor loop)
# Exits match a strong optimizer draw; entry thresholds are looser than that draw to force more buys.
# (Optimizer had buy_min_imbalance 0.4166 / buy_min_price_delta 0.0003 — lowered here.)
BUY_MIN_IMBALANCE = 0.24
BUY_MIN_PRICE_DELTA = 0.00012

# Stored snapshots often have spread ~0.57–1.0; optimizer suggested 0.5288 but that blocks every tick.
# 1.0 effectively disables the spread gate for paper; tighten for live tight books.
MAX_SPREAD = 1.0

# Require this many consecutive qualifying ticks (each TICK seconds apart)
SIGNAL_CONFIRM_TICKS = 1

# Exit: open positions when marked price moves this far vs entry (paper / backtest).
EXIT_TAKE_PROFIT_MULT = 1.0649
EXIT_STOP_LOSS_MULT = 0.7446

# Portfolio caps
MAX_OPEN_POSITIONS = 5
MAX_POSITIONS_PER_TOPIC = 2

# Gamma screening (client-side filters after fetch)
MIN_LIQUIDITY = 25_000
MIN_VOLUME_24HR = 10_000

# Candidate universe (poll many; trade few)
CANDIDATE_MARKETS_MIN = 20
CANDIDATE_MARKETS_MAX = 30

# Diversification: at least this many per primary topic before filling remainder
MIN_MARKETS_PER_TOPIC = 2

# Soft cap per topic in the candidate monitor list (avoid 10× same bucket)
MAX_CANDIDATES_PER_TOPIC = 6
