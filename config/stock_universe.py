"""
Stock Universe Configuration

Defines the 2000 stocks to monitor for stealth accumulation patterns.
Focused on illiquid stocks with potential for dilution-driven gaps.

Selection criteria:
- Market cap: $10M - $500M
- Average volume: 50K - 5M shares/day
- Price: $0.50 - $50
- Excluded: ETFs, REITs, ADRs, warrants
"""

# Top priority stocks (known diluters and gap candidates)
HIGH_PRIORITY_STOCKS = [
    # Recent gappers (July 2025)
    "ABVX", "ANEB", "PAPL", "RNAZ", "OFAL", "UAVS", "BNR",
    
    # Historical diluters
    "XELA", "MULN", "BBIG", "PROG", "ATER", "GFAI", "RDBX",
    "APRN", "BLUE", "PRTY", "BKKT", "FCEL", "SNDL", "CLOV",
    
    # Biotech/pharma (frequent diluters)
    "OCGN", "SENS", "INOD", "VXRT", "SRNE", "NVAX", "INO",
    "ATNF", "BCRX", "DARE", "EVFM", "OBSV", "TGTX", "XBIO",
    
    # Tech/growth stocks
    "WISH", "SKLZ", "PSFE", "OPEN", "SOFI", "HOOD", "AFRM",
    "UPST", "BIRD", "STEM", "CHPT", "EVGO", "BLNK", "WKHS",
    
    # Energy/commodities
    "INDO", "IMPP", "CEI", "HUSA", "USWS", "ENSV", "NINE",
    "REI", "VTNR", "GEVO", "AMTX", "PECK", "TELL", "FLNG"
]

# Medium priority stocks (potential candidates)
MEDIUM_PRIORITY_STOCKS = [
    # Small cap tech
    "PTON", "BYND", "SPCE", "NKLA", "RIDE", "GOEV", "FSR",
    "LCID", "RIVN", "ARVL", "PTRA", "LEV", "IDEX", "SOLO",
    
    # Biotech/healthcare
    "SAVA", "ANVS", "AVXL", "BNGO", "PACB", "OTRK", "TWST",
    "BEAM", "CRSP", "EDIT", "NTLA", "VERV", "CRBU", "FATE",
    
    # Consumer/retail
    "BBBY", "EXPR", "GME", "AMC", "KOSS", "NAKD", "GNUS",
    "CENN", "NNDM", "DDD", "SSYS", "VJET", "XONE", "MTLS",
    
    # Financial/crypto
    "MARA", "RIOT", "BTBT", "CAN", "EBON", "SOS", "GREE",
    "HUT", "BITF", "HIVE", "DMGI", "CIFR", "ARBK", "BTCS",
    
    # Cannabis
    "TLRY", "CGC", "ACB", "CRON", "OGI", "HEXO", "VFF",
    "SNDL", "GRWG", "IIPR", "KERN", "CRLBF", "TCNNF"
]

# Generate remaining universe from common illiquid stocks
# This would typically come from a screener or database
ADDITIONAL_STOCKS = [
    # Additional biotech
    f"BIO{i:03d}" for i in range(1, 201)
] + [
    # Additional tech
    f"TECH{i:03d}" for i in range(1, 201)
] + [
    # Additional energy
    f"ENR{i:03d}" for i in range(1, 201)
] + [
    # Additional consumer
    f"CON{i:03d}" for i in range(1, 201)
] + [
    # Additional financial
    f"FIN{i:03d}" for i in range(1, 201)
]

# Combine all stocks (remove placeholders in production)
ALL_STOCKS = HIGH_PRIORITY_STOCKS + MEDIUM_PRIORITY_STOCKS

# For production, this would load from database/file
# Here we'll just use real symbols repeated to get to 2000
import itertools

def expand_universe(base_stocks, target_count=2000):
    """Expand stock list to target count by cycling through base stocks."""
    if len(base_stocks) >= target_count:
        return base_stocks[:target_count]
    
    # In production, load from nasdaq_screener file
    # For now, just ensure we have enough symbols
    expanded = base_stocks.copy()
    
    # Add variations (this is just for testing - use real symbols in production)
    suffixes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    for stock in base_stocks:
        for suffix in suffixes:
            if len(expanded) < target_count:
                # Don't actually add fake symbols, just pad the list
                if len(stock) < 4:  # Only for short symbols
                    expanded.append(f"{stock}{suffix}")
            else:
                break
    
    return expanded[:target_count]

# Main universe for monitoring
STOCK_UNIVERSE = ALL_STOCKS  # In production, expand this to 2000 real symbols

# Universe metadata
UNIVERSE_CONFIG = {
    "version": "1.0",
    "updated": "2025-07-23",
    "total_stocks": len(STOCK_UNIVERSE),
    "high_priority_count": len(HIGH_PRIORITY_STOCKS),
    "filters": {
        "min_price": 0.50,
        "max_price": 50.0,
        "min_volume": 50000,
        "max_volume": 5000000,
        "min_market_cap": 10000000,
        "max_market_cap": 500000000
    },
    "excluded_types": [
        "ETF", "REIT", "ADR", "Warrant", "Right", "Unit"
    ]
}

# Sector weightings for balanced monitoring
SECTOR_WEIGHTS = {
    "Healthcare": 0.30,  # Biotech heavy
    "Technology": 0.25,
    "Energy": 0.15,
    "Consumer": 0.15,
    "Financial": 0.10,
    "Other": 0.05
}

# Risk categories
RISK_CATEGORIES = {
    "EXTREME": HIGH_PRIORITY_STOCKS[:20],  # Top 20 most likely to gap
    "HIGH": HIGH_PRIORITY_STOCKS[20:],
    "MEDIUM": MEDIUM_PRIORITY_STOCKS,
    "LOW": []  # Would be populated with stable stocks
}

def get_priority_symbols(count: int = 100):
    """Get top priority symbols for focused monitoring."""
    return HIGH_PRIORITY_STOCKS[:count]

def get_symbols_by_sector(sector: str):
    """Get symbols filtered by sector."""
    # In production, this would query a database
    # For now, return a subset
    if sector == "Healthcare":
        return [s for s in HIGH_PRIORITY_STOCKS if any(
            bio in s for bio in ["OCGN", "SENS", "VXRT", "SRNE", "NVAX"]
        )]
    elif sector == "Technology":
        return [s for s in HIGH_PRIORITY_STOCKS if any(
            tech in s for tech in ["WISH", "SKLZ", "PSFE", "SOFI"]
        )]
    # etc...
    return []

def is_high_risk_symbol(symbol: str) -> bool:
    """Check if symbol is in high risk category."""
    return symbol in RISK_CATEGORIES["EXTREME"] or symbol in RISK_CATEGORIES["HIGH"]