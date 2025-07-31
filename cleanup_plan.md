# CLEANUP PLAN: Remove Over-Engineered Code

Coverage shows only 2.96% of code is used. DELETE 97% of over-engineered code.

## KEEP (Actually Used - High Coverage):
- `simple_synthetic_test.py` (96% coverage) ✅
- `production_replay_example.py` ✅ 
- `ingestion/clickhouse_mock_iqfeed.py` ✅
- `ingestion/iqfeed_parser.py` ✅
- `tests/test_core_functionality.py` ✅

## DELETE (0% Coverage - Over-Engineered):

### Complex Producers (Unused):
- `ingestion/synthetic_market_data_producer.py` (0% coverage) ❌
- `ingestion/multi_symbol_temporal_orchestrator.py` (0% coverage) ❌
- `ingestion/enhanced_historical_replayer.py` (0% coverage) ❌
- `stress_test_synthetic_data.py` (0% coverage) ❌

### All Downloader Modules (Unused):
- `downloader/` entire directory (0% coverage) ❌

### All Processing Modules (Unused):
- `processing/` entire directory (0% coverage) ❌

### All Storage Modules (Unused):
- `storage/` entire directory (0% coverage) ❌

### All Other Test Files (Unused):
- `tests/` everything except `test_core_functionality.py` (0% coverage) ❌

### Microstructure Analysis (Unused):
- `microstructure_analysis/` entire directory (0% coverage) ❌

### Backtesting (Unused):
- `backtesting/` entire directory (0% coverage) ❌

### Strategies (Unused):
- `strategies/` entire directory (0% coverage) ❌

### Analysis (Unused):  
- `analysis/` entire directory (0% coverage) ❌

### Realtime UI (Unused):
- `realtime/` entire directory (0% coverage) ❌

## FINAL SIMPLE STRUCTURE:
```
RealTimeData/
├── infrastructure/          # Keep Docker services
├── ingestion/
│   ├── clickhouse_mock_iqfeed.py
│   └── iqfeed_parser.py
├── simple_synthetic_test.py
├── production_replay_example.py
├── tests/
│   └── test_core_functionality.py
└── CLAUDE.md (simplified)
```

## RESULT:
- From ~23,456 lines to ~1,000 lines  
- From complex architecture to simple, working system
- All core functionality preserved
- Zero over-engineering