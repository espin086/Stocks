# 0001 — Tasks

Estimates are focused hours. Each task names the test that proves it.

## Wave A — skeleton (parallel-safe)

- [x] **A1. Errors and exit codes** (1h)
      `core/errors.py`: the exception tree from `design.md`, each with an
      `exit_code` class attribute.
      → `tests/test_errors.py::test_exit_code_mapping_is_exhaustive`
- [x] **A2. Config resolution** (2h)
      `config.py`: flag → env → `config.toml` → default. `Settings` as a pydantic
      model. Secret masking helper.
      → `tests/test_config.py::test_precedence_chain`, `::test_secrets_masked`
- [x] **A3. Rendering** (2h)
      `cli/render.py`: `render(obj, fmt, stream)` for table/json/csv; TTY detection;
      per-column precision rules.
      → `tests/test_render.py::test_json_is_sole_stdout_document`,
        `::test_non_tty_defaults_to_csv`
- [x] **A3b. Command registry** (3h)
      `registry.py`: `Command`, `register`, shared parameter types (`TickerList`,
      `Frequency`, `Weights`, `Currency`), the Typer generator, `sobres commands`.
      → `tests/cli/test_registry.py::test_typer_app_has_one_subcommand_per_registration`,
        `::test_defaults_come_only_from_param_model`,
        `::test_cross_field_validator_rejects_weight_count_mismatch`,
        `::test_registration_count_matches_explicit_list`
- [x] **A3c. Test scaffolding** (2h)
      `tests/architecture/` import scanners and literal checks;
      `tests/invariants/` iterating the registry; `scripts/record_fixtures.py`
      skeleton; scenario-coverage test (advisory until a change is marked
      implemented).
      → `tests/architecture/test_layering.py`,
        `tests/invariants/test_every_command.py`
- [x] **A4. Structured logging** (3h)
      `observability/logging.py`: structlog wired to stderr, human renderer on a
      TTY and JSON otherwise, run-id binding, third-party loggers routed and
      defaulted to WARNING.
      → `tests/test_logging.py::test_all_records_go_to_stderr`,
        `::test_json_output_parseable_at_debug_level`,
        `::test_run_id_on_every_record`
- [x] **A5. Redaction** (2h)
      Formatter-level scrubbing by key name and URL credential stripping, applied
      to log records and span attributes alike.
      → `tests/test_redaction.py::test_sentinel_credential_never_in_stderr`
        (parametrized over every command, at DEBUG)
      → `::test_api_key_stripped_from_logged_url`
- [x] **A6. Tracing** (3h)
      `observability/tracing.py`: OTel API with the no-op default, SDK behind the
      `otel` extra, `OTEL_*` activation, trace/span ids bound into log records,
      exporter failure warns once and never raises.
      → `tests/test_tracing.py::test_noop_by_default_without_sdk`,
        `::test_exporter_failure_does_not_fail_command`,
        `::test_records_carry_trace_id_when_active`
- [x] **A7. Observability cannot change results** (1h)
      → `tests/test_observability_invariants.py::test_stdout_identical_across_log_levels`,
        `::test_stdout_identical_with_and_without_tracing`

## Wave B — storage and data layer (A1 must land first)

- [x] **B0. Storage port** (3h)
      `data/storage/base.py`: `ObservationStore` / `KeyValueStore` protocols
      phrased in domain terms, the backend registry, and `SOBRES_DB_URL`
      resolution.
      → `tests/data/test_storage_port.py::test_unknown_url_scheme_exits_3_listing_backends`
      → `tests/test_architecture.py::test_db_drivers_imported_only_in_adapters`
- [x] **B0b. Conformance suite** (3h)
      `tests/data/storage_conformance.py`: round-trip, upsert semantics,
      transaction rollback, concurrent reader during write, error translation.
      Parametrized over a fixture list of registered adapters.
      → runs against the SQLite adapter now; adding a backend later means one
        fixture-list entry and nothing else
      *Write this before the adapter. It is the artifact that makes the second
      backend cheap, and it is only honest while there is one implementation.*
- [x] **B0c. SQLite adapter** (3h)
      `data/storage/adapters/sqlite.py`: SQLAlchemy Core engine, WAL/busy-timeout/
      foreign-key pragmas confined here, driver-exception translation to the 0001
      taxonomy, bounded retry with backoff on contention.
      → the conformance suite, plus
        `::test_locked_database_retries_then_raises_translated_error`
- [x] **B0d. Portability guards** (1.5h)
      Schema restricted to the portable type set; application-generated ids;
      explicit UTC timestamps; JSON stored as text.
      → `tests/data/test_portability.py::test_schema_uses_only_portable_types`,
        `::test_timestamps_round_trip_as_utc_aware`,
        `::test_no_backend_specific_sql_outside_adapters`

- [x] **B1. Protocols and canonical frame** (2.5h)
      `data/base.py`: the four protocols, `PriceField`, and
      `validate_price_frame()` enforcing the canonical shape plus the data-quality
      rules: non-positive price, non-finite value, implausible move flagged in
      `attrs`, adjustment-factor monotonicity.
      → `tests/data/test_base.py::test_validate_rejects_tz_aware_index` (+ duplicate
        index, non-float dtype, descending index, non-positive price)
      → `::test_implausible_move_kept_and_flagged`,
        `::test_adjustment_factor_violation_flagged`
- [x] **B1b. Missing-data policy** (1.5h)
      Gap classification (closed / not listed / delisted / provider gap); fill
      policy with no default; alignment records what it dropped.
      → `tests/data/test_gaps.py::test_only_provider_gaps_are_fillable`,
        `::test_fill_policy_has_no_default`,
        `::test_alignment_records_dropped_counts_per_source`
- [x] **B2. Cache over the storage port** (3h)
      `data/cache.py`: observation upsert keyed
      `(provider, dataset, symbol, date)`, `fetch_log` ranges, per-dataset TTL,
      `--refresh` bypass, integrity check on open — all through `ObservationStore`,
      importing no driver.
      → `tests/data/test_cache.py::test_hit_avoids_fetch`, `::test_ttl_expiry`,
        `::test_subrange_of_cached_range_makes_no_network_call`,
        `::test_extension_fetches_only_the_missing_tail`,
        `::test_refetch_overwrites_revised_values`,
        `::test_corrupt_database_exits_without_recreating`
- [x] **B3. Alignment** (1.5h)
      `data/align.py`: `align_frames(*frames, how)`, tz normalization, empty-overlap
      → `AlignmentError`.
      → `tests/data/test_align.py::test_inner_join_on_trading_days`,
        `::test_empty_overlap_raises`
- [x] **B4. yfinance provider** (2h)
      `data/yfinance_provider.py`. Adjusted close default; `UnknownTickerError`;
      `ProviderError` wrapping; `attrs` provenance.
      → `tests/data/test_yfinance.py` against recorded fixtures
      → plus the shared `contract_test_price_provider` suite
- [x] **B5. FRED provider** (2h)
      `data/fred_provider.py` + `get_risk_free_rate()` with the percent→decimal
      conversion.
      → `tests/data/test_fred.py::test_missing_key_exits_3_with_guidance`,
        `::test_risk_free_converted_to_decimal`
- [x] **B5b. Currency model** (2.5h)
      `data/currency.py`: `Currency`, `CurrencyPair(base, quote)`, sub-unit
      normalization, `convert()` as the only way to apply a rate.
      → `tests/data/test_currency.py::test_round_trip_conversion_is_exact`,
        `::test_pence_quoted_listing_normalized_to_major_unit`,
        `::test_cross_rate_consistent_with_its_two_legs`,
        `::test_mixed_currency_without_target_raises_usage_error`
- [x] **B5c. FX provider** (2.5h)
      `data/ecb_provider.py` implementing `FxProvider`, keyless; FRED `DEX*` as
      the alternative; carry-forward on non-trading days, recorded.
      → `tests/data/test_fx.py::test_carry_forward_recorded_not_silent`,
        plus the shared provider contract suite
- [x] **B6. Ken French provider** (3h)
      `data/ken_french.py`: zip fetch, multi-table CSV parsing, `ff3`/`ff5`/`ff5+mom`,
      percent→decimal, loud failure on unexpected layout.
      → `tests/data/test_ken_french.py::test_ff5_columns_exact`,
        `::test_known_month_matches_published_value`,
        `::test_unexpected_layout_raises_provider_error`
      *Highest-uncertainty task in this change — the CSV layout is irregular. Do it
      early enough that surprises don't land at the end.*

## Wave C — CLI surface (B must land first)

- [x] **C1. Root app and error boundary** (1.5h)
      `cli/main.py`: `--version`, `--debug`, `--format`, `--refresh`, `-v/-vv`,
      `--log-level`, `--log-format`; a single handler mapping `SobresError` →
      message + exit code, with the run id in the message.
      → `tests/cli/test_main.py::test_version`, `::test_bare_shows_help_exit_0`,
        `::test_provider_error_exits_4_without_traceback`
- [x] **C2. `sobres data` group** (2h) — `prices`, `macro`, `factors`, `fx`, each a
      registry declaration; no hand-written Typer command.
      → `tests/cli/test_data_commands.py` (one test per subcommand × 3 formats)
- [x] **C3. `sobres cache` group** (1h) — `info`, `clear` (with confirm + `--yes`).
      Cache-only; the wider `sobres db` group arrives with 0003.
      → `tests/cli/test_cache_commands.py::test_clear_requires_confirmation`
- [x] **C4. `sobres config` group** (1h) — `set`, `show` (masked), `path`.
      → `tests/cli/test_config_commands.py::test_show_masks_api_keys`
- [x] **C4b. Settings registry** (2h)
      `settings.py`: `@setting` declarations with env, secret, required,
      description, obtain, optional live validator; `sobres config set|show`
      re-pointed at it.
      → `tests/cli/test_settings.py::test_every_env_var_read_is_a_declared_setting`,
        `::test_config_show_masks_secrets_to_last_four`
- [x] **C4c. `sobres init`** (3h)
      Rich-prompt wizard over the registry; no-echo secrets; idempotent re-run
      showing masked current values; live validation with consent;
      `--non-interactive`; sets up storage; ends by running doctor and printing
      one first command; first-run hint on other commands.
      → `tests/cli/test_init.py::test_rerun_without_changes_is_byte_identical`,
        `::test_non_interactive_missing_required_exits_3_naming_it`,
        `::test_failed_live_validation_never_stores_silently`,
        `::test_ends_by_running_doctor`
- [x] **C4d. `sobres doctor`** (3h)
      `Check` registry with `run` and optional `fix`; the 0001 check set;
      grouped TTY rendering and `--format json`; exit 0/1 with `--strict`;
      `--offline`; 5s network caps; `--fix` never touches secrets.
      → `tests/cli/test_doctor.py::test_every_setting_and_provider_has_a_check`,
        `::test_failure_lines_always_carry_a_next_step`,
        `::test_offline_skips_rather_than_fails`,
        `::test_fix_never_writes_a_secret`,
        `::test_warnings_do_not_change_exit_code_without_strict`
- [x] **C4e. `sobres upgrade`** (1h)
      Installer detection (pip / pipx / uv / container); exact command;
      confirmation; `--check`.
      → `tests/cli/test_upgrade.py::test_detects_installer_and_prints_matching_command`
- [x] **C5. Disclaimer footer** (0.5h) — table format only.
      → `tests/cli/test_disclaimer.py::test_absent_from_json_and_csv`

## Wave D — release readiness

- [x] **D1. Fixture recording script** (1h)
      `scripts/record_fixtures.py` — regenerates `tests/fixtures/` deliberately, so
      re-recording is a reviewable diff rather than an ad-hoc action.
      *The current fixtures were synthesized in each vendor's payload shape by
      `scripts/synthesize_fixtures.py` because no provider was reachable from the
      implementing environment; see `tests/fixtures/README.md`. Re-record live.*
- [x] **D2. README quickstart** (1h) — install, the three `sobres data` commands, the
      no-key promise, and the not-advice disclaimer.
- [x] **D3. CI green** (1.5h) — ruff, ruff format, mypy --strict, pytest; the
      build job's clean-venv smoke extended to `sobres init --non-interactive` →
      `sobres doctor --offline` → one data command on a fixture.
- [ ] **D4. Port reuse audit** (1h) — *deferred: the `NewsWaveMetrics` repository
      was not reachable from the implementing environment; revisit when it is.*
      Diff `NewsWaveMetrics/fetch_yfinance.py` and `extract_economic_data.py` against
      B4/B5; lift anything that handles a real-world edge case these specs missed.

- [x] **C6. Instrumented adapters** (2h)
      Spans and logs around provider fetches, storage operations, and core calls,
      per the placement rule in `design.md`.
      → `tests/test_architecture.py::test_core_imports_no_logging_or_tracing`

**Total: ~67h** (was ~27h; the storage port and observability added ~19h, the
currency model ~5h, the registry, test scaffolding, and data quality ~7h,
onboarding ~9h). Wave B is the critical path; B6 and B0b are the tasks with
real unknowns.

## Definition of done

- [x] `pip install sobres` with no keys → `sobres data prices AAPL` works
- [x] No database driver is imported outside `data/storage/adapters/`
- [x] The conformance suite passes against the SQLite adapter
- [x] `core/` imports no logging, tracing, network, or database module
- [x] A sentinel credential appears nowhere in stderr at DEBUG, for any command
- [x] stdout is byte-identical across log levels and with tracing on and off
- [x] No call site outside `data/currency.py` multiplies or divides by a rate
- [x] A single-currency run fetches no rates and matches a no-conversion build
- [x] `pip install` → `sobres init --non-interactive` → `sobres doctor --offline` exits 0 in a clean venv, in CI
- [x] Every env var the code reads is a declared setting; every setting and provider has a doctor check
- [x] No Typer command exists that is not a registry declaration
- [x] `tests/architecture/` and `tests/invariants/` run against every registered command
- [x] `pytest -m "not network"` passes with networking disabled
- [x] `mypy --strict` clean
- [x] Every scenario in both spec deltas has a test that references it
- [x] A second identical `sobres data prices` call is served from cache in < 1s
