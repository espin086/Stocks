# 0001 — Tasks

Estimates are focused hours. Each task names the test that proves it.

## Wave A — skeleton (parallel-safe)

- [ ] **A1. Errors and exit codes** (1h)
      `core/errors.py`: the exception tree from `design.md`, each with an
      `exit_code` class attribute.
      → `tests/test_errors.py::test_exit_code_mapping_is_exhaustive`
- [ ] **A2. Config resolution** (2h)
      `config.py`: flag → env → `config.toml` → default. `Settings` as a pydantic
      model. Secret masking helper.
      → `tests/test_config.py::test_precedence_chain`, `::test_secrets_masked`
- [ ] **A3. Rendering** (2h)
      `cli/render.py`: `render(obj, fmt, stream)` for table/json/csv; TTY detection;
      per-column precision rules.
      → `tests/test_render.py::test_json_is_sole_stdout_document`,
        `::test_non_tty_defaults_to_csv`

## Wave B — data layer (A1 must land first)

- [ ] **B1. Protocols and canonical frame** (2h)
      `data/base.py`: the three protocols, `PriceField`, and
      `validate_price_frame()` enforcing the canonical shape.
      → `tests/data/test_base.py::test_validate_rejects_tz_aware_index` (+ duplicate
        index, non-float dtype, descending index)
- [ ] **B2. Cache** (2h)
      `data/cache.py`: content-addressed parquet + `.meta.json`, per-entry TTL,
      `--refresh` bypass, corrupt-entry self-heal.
      → `tests/data/test_cache.py::test_hit_avoids_fetch`, `::test_ttl_expiry`,
        `::test_corrupt_entry_refetches_and_warns`
- [ ] **B3. Alignment** (1.5h)
      `data/align.py`: `align_frames(*frames, how)`, tz normalization, empty-overlap
      → `AlignmentError`.
      → `tests/data/test_align.py::test_inner_join_on_trading_days`,
        `::test_empty_overlap_raises`
- [ ] **B4. yfinance provider** (2h)
      `data/yfinance_provider.py`. Adjusted close default; `UnknownTickerError`;
      `ProviderError` wrapping; `attrs` provenance.
      → `tests/data/test_yfinance.py` against recorded fixtures
      → plus the shared `contract_test_price_provider` suite
- [ ] **B5. FRED provider** (2h)
      `data/fred_provider.py` + `get_risk_free_rate()` with the percent→decimal
      conversion.
      → `tests/data/test_fred.py::test_missing_key_exits_3_with_guidance`,
        `::test_risk_free_converted_to_decimal`
- [ ] **B6. Ken French provider** (3h)
      `data/ken_french.py`: zip fetch, multi-table CSV parsing, `ff3`/`ff5`/`ff5+mom`,
      percent→decimal, loud failure on unexpected layout.
      → `tests/data/test_ken_french.py::test_ff5_columns_exact`,
        `::test_known_month_matches_published_value`,
        `::test_unexpected_layout_raises_provider_error`
      *Highest-uncertainty task in this change — the CSV layout is irregular. Do it
      early enough that surprises don't land at the end.*

## Wave C — CLI surface (B must land first)

- [ ] **C1. Root app and error boundary** (1.5h)
      `cli/main.py`: `--version`, `--debug`, `--format`, `--refresh`; a single
      handler mapping `QuantfolioError` → message + exit code.
      → `tests/cli/test_main.py::test_version`, `::test_bare_shows_help_exit_0`,
        `::test_provider_error_exits_4_without_traceback`
- [ ] **C2. `qf data` group** (2h) — `prices`, `macro`, `factors`.
      → `tests/cli/test_data_commands.py` (one test per subcommand × 3 formats)
- [ ] **C3. `qf cache` group** (1h) — `info`, `clear` (with confirm + `--yes`).
      → `tests/cli/test_cache_commands.py::test_clear_requires_confirmation`
- [ ] **C4. `qf config` group** (1h) — `set`, `show` (masked), `path`.
      → `tests/cli/test_config_commands.py::test_show_masks_api_keys`
- [ ] **C5. Disclaimer footer** (0.5h) — table format only.
      → `tests/cli/test_disclaimer.py::test_absent_from_json_and_csv`

## Wave D — release readiness

- [ ] **D1. Fixture recording script** (1h)
      `scripts/record_fixtures.py` — regenerates `tests/fixtures/` deliberately, so
      re-recording is a reviewable diff rather than an ad-hoc action.
- [ ] **D2. README quickstart** (1h) — install, the three `qf data` commands, the
      no-key promise, and the not-advice disclaimer.
- [ ] **D3. CI green** (1h) — ruff, ruff format, mypy --strict, pytest on 3.11+3.12.
- [ ] **D4. Port reuse audit** (1h)
      Diff `NewsWaveMetrics/fetch_yfinance.py` and `extract_economic_data.py` against
      B4/B5; lift anything that handles a real-world edge case these specs missed.

**Total: ~27h.** Wave B is the critical path; B6 is the only task with real
unknowns.

## Definition of done

- [ ] `pip install quantfolio` with no keys → `qf data prices AAPL` works
- [ ] `pytest -m "not network"` passes with networking disabled
- [ ] `mypy --strict` clean
- [ ] Every scenario in both spec deltas has a test that references it
- [ ] A second identical `qf data prices` call is served from cache in < 1s
