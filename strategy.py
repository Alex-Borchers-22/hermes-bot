"""Trading / screening knobs (paper trading — tune freely)."""

# Entry signal (aligned momentum — see monitor loop)
BUY_MIN_IMBALANCE = 0.65
BUY_MIN_PRICE_DELTA = 0.02

# Liquidity / execution quality
MAX_SPREAD = 0.04

# Require this many consecutive qualifying ticks (each TICK seconds apart)
SIGNAL_CONFIRM_TICKS = 2

# Exit: open positions when marked price moves this far vs entry (paper / backtest).
EXIT_TAKE_PROFIT_MULT = 1.12
EXIT_STOP_LOSS_MULT = 0.88

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
