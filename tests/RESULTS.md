# Test results

Recorded on 2026-10-17 from the repository root, after generating the data with `python3 data/generate.py`.

| Python | Schema validation | Tests run | Result |
| --- | --- | --- | --- |
| 3.14.6 | with the draft schema (`COGNIC_SAFETY_SCHEMA` set) | 117 | OK |
| 3.14.6 | without the schema | 117 | OK, 1 skipped (the schema test) |
| 3.9.6 | with the draft schema | 117 | OK |

Commands:

```bash
python3 -m unittest discover -s tests -t .
COGNIC_SAFETY_SCHEMA=/path/to/draft-schema.json python3 -m unittest discover -s tests -t . -v
```

What the suite covers:

- `test_tags`: every tag fires on its positive case and not on its near miss; positives sit on the threshold and near misses just below it.
- `test_expected_tags`: the engine's tags for the 42 labelled synthetic customers equal `data/expected_tags.json`.
- `test_edge_cases`: no transactions, new customers, missing fields, currency conversion and unknown currencies, sign conventions and conflicts, rows after the as-of date, duplicates, protected columns ignored.
- `test_taxonomy`: shape, fairness guard (protected traits, age, proxy categories), strict validation, rules read from the file.
- `test_cli`: byte-identical reruns, print-only mode writes nothing, no network, randomness or clock in the engine, no model names in code or config.
- `test_generator`: the seed reproduces the committed data byte for byte, and all identifiers are synthetic.
- `test_safety_file`, `test_schema_validator`: the safety file matches the plugin and validates against the draft schema; the validator rejects each keyword's violations.

Full output (Python 3.14.6, with the draft schema):

```text
test_errors_exit_with_status_2 (tests.test_cli.Commands.test_errors_exit_with_status_2) ... ok
test_json_for_one_customer (tests.test_cli.Commands.test_json_for_one_customer) ... ok
test_list_tags (tests.test_cli.Commands.test_list_tags) ... ok
test_text_explanation (tests.test_cli.Commands.test_text_explanation) ... ok
test_why_explains_a_tag_that_does_not_apply (tests.test_cli.Commands.test_why_explains_a_tag_that_does_not_apply) ... ok
test_two_runs_write_byte_identical_files (tests.test_cli.Determinism.test_two_runs_write_byte_identical_files) ... ok
test_out_dir_never_overwrites_an_input (tests.test_cli.ReadOnly.test_out_dir_never_overwrites_an_input) ... ok
test_print_only_mode_writes_nothing (tests.test_cli.ReadOnly.test_print_only_mode_writes_nothing) ... ok
test_engine_has_no_network_randomness_or_clock (tests.test_cli.StaticGuarantees.test_engine_has_no_network_randomness_or_clock) ... ok
test_no_model_names_in_code_or_config (tests.test_cli.StaticGuarantees.test_no_model_names_in_code_or_config) ... ok
test_empty_currency_means_the_customers_home_currency (tests.test_edge_cases.Currency.test_empty_currency_means_the_customers_home_currency) ... ok
test_foreign_amounts_are_converted_before_thresholds (tests.test_edge_cases.Currency.test_foreign_amounts_are_converted_before_thresholds) ... ok
test_foreign_currency_flag_uses_the_home_currency (tests.test_edge_cases.Currency.test_foreign_currency_flag_uses_the_home_currency) ... ok
test_lower_case_currency_is_accepted (tests.test_edge_cases.Currency.test_lower_case_currency_is_accepted) ... ok
test_unknown_currency_is_skipped_never_guessed (tests.test_edge_cases.Currency.test_unknown_currency_is_skipped_never_guessed) ... ok
test_bad_open_date_is_reported (tests.test_edge_cases.MissingFields.test_bad_open_date_is_reported) ... ok
test_empty_category_and_channel_get_defaults (tests.test_edge_cases.MissingFields.test_empty_category_and_channel_get_defaults) ... ok
test_missing_home_country_blocks_abroad_rules_only (tests.test_edge_cases.MissingFields.test_missing_home_country_blocks_abroad_rules_only) ... ok
test_missing_open_date_means_not_evaluated_not_guessed (tests.test_edge_cases.MissingFields.test_missing_open_date_means_not_evaluated_not_guessed) ... ok
test_missing_required_column_is_an_error (tests.test_edge_cases.MissingFields.test_missing_required_column_is_an_error) ... ok
test_only_required_transaction_columns (tests.test_edge_cases.MissingFields.test_only_required_transaction_columns) ... ok
test_rows_missing_date_or_amount_are_skipped_and_counted (tests.test_edge_cases.MissingFields.test_rows_missing_date_or_amount_are_skipped_and_counted) ... ok
test_account_opened_after_as_of_is_not_new (tests.test_edge_cases.NewCustomer.test_account_opened_after_as_of_is_not_new) ... ok
test_new_customer_is_not_dormant_or_falling (tests.test_edge_cases.NewCustomer.test_new_customer_is_not_dormant_or_falling) ... ok
test_new_customer_with_no_transactions (tests.test_edge_cases.NewCustomer.test_new_customer_with_no_transactions) ... ok
test_customer_without_transactions_gets_only_tenure_tags (tests.test_edge_cases.NoTransactions.test_customer_without_transactions_gets_only_tenure_tags) ... ok
test_empty_transactions_file_needs_an_explicit_as_of (tests.test_edge_cases.NoTransactions.test_empty_transactions_file_needs_an_explicit_as_of) ... ok
test_protected_columns_are_never_loaded_and_change_nothing (tests.test_edge_cases.ProtectedColumns.test_protected_columns_are_never_loaded_and_change_nothing) ... ok
test_default_as_of_is_the_latest_transaction_date (tests.test_edge_cases.RowsOutsideTheData.test_default_as_of_is_the_latest_transaction_date) ... ok
test_mid_month_as_of_uses_complete_months_only (tests.test_edge_cases.RowsOutsideTheData.test_mid_month_as_of_uses_complete_months_only) ... ok
test_transactions_after_as_of_are_ignored_and_counted (tests.test_edge_cases.RowsOutsideTheData.test_transactions_after_as_of_are_ignored_and_counted) ... ok
test_unknown_customer_and_duplicate_ids (tests.test_edge_cases.RowsOutsideTheData.test_unknown_customer_and_duplicate_ids) ... ok
test_negative_credit_is_a_sign_conflict (tests.test_edge_cases.Signs.test_negative_credit_is_a_sign_conflict) ... ok
test_positive_amount_without_direction_is_a_credit (tests.test_edge_cases.Signs.test_positive_amount_without_direction_is_a_credit) ... ok
test_signed_and_unsigned_conventions_give_the_same_tags (tests.test_edge_cases.Signs.test_signed_and_unsigned_conventions_give_the_same_tags) ... ok
test_unknown_direction_and_zero_amount_are_skipped (tests.test_edge_cases.Signs.test_unknown_direction_and_zero_amount_are_skipped) ... ok
test_as_of_matches (tests.test_expected_tags.ExpectedTags.test_as_of_matches) ... ok
test_labelled_customers_get_exactly_their_expected_tags (tests.test_expected_tags.ExpectedTags.test_labelled_customers_get_exactly_their_expected_tags) ... ok
test_labelled_subset_covers_every_tag (tests.test_expected_tags.ExpectedTags.test_labelled_subset_covers_every_tag) ... ok
test_labelled_subset_includes_customers_with_no_tags (tests.test_expected_tags.ExpectedTags.test_labelled_subset_includes_customers_with_no_tags) ... ok
test_malformed_rows_are_reported (tests.test_expected_tags.ExpectedTags.test_malformed_rows_are_reported) ... ok
test_a_different_seed_changes_the_background (tests.test_generator.Reproducible.test_a_different_seed_changes_the_background) ... ok
test_same_seed_gives_byte_identical_files (tests.test_generator.Reproducible.test_same_seed_gives_byte_identical_files) ... ok
test_customer_columns_hold_no_protected_traits (tests.test_generator.SyntheticOnly.test_customer_columns_hold_no_protected_traits) ... ok
test_identifiers_are_obviously_synthetic (tests.test_generator.SyntheticOnly.test_identifiers_are_obviously_synthetic) ... ok
test_size (tests.test_generator.SyntheticOnly.test_size) ... ok
test_twelve_months (tests.test_generator.SyntheticOnly.test_twelve_months) ... ok
test_declares_read_only_and_confidential_personal_data (tests.test_safety_file.SafetyFile.test_declares_read_only_and_confidential_personal_data) ... ok
test_every_component_is_declared_and_exists (tests.test_safety_file.SafetyFile.test_every_component_is_declared_and_exists) ... ok
test_identity_matches_the_plugin_manifest (tests.test_safety_file.SafetyFile.test_identity_matches_the_plugin_manifest) ... ok
test_skill_and_command_files (tests.test_safety_file.SafetyFile.test_skill_and_command_files) ... ok
test_valid_against_the_draft_schema (tests.test_safety_file.SafetyFile.test_valid_against_the_draft_schema) ... ok
test_each_keyword_rejects (tests.test_schema_validator.ValidatorTest.test_each_keyword_rejects) ... ok
test_integer_and_bool_are_distinct (tests.test_schema_validator.ValidatorTest.test_integer_and_bool_are_distinct) ... ok
test_unsupported_keyword_never_passes_silently (tests.test_schema_validator.ValidatorTest.test_unsupported_keyword_never_passes_silently) ... ok
test_valid_document (tests.test_schema_validator.ValidatorTest.test_valid_document) ... ok
test_every_taxonomy_tag_has_a_positive_and_a_near_miss (tests.test_tags.EveryTagHasCases.test_every_taxonomy_tag_has_a_positive_and_a_near_miss) ... ok
test_all_tags (tests.test_tags.PositiveAndNearMiss.test_all_tags) ... ok
test_reason_is_filled_and_rule_is_shown (tests.test_tags.PositiveAndNearMiss.test_reason_is_filled_and_rule_is_shown) ... ok
test_saver_surplus_branch (tests.test_tags.PositiveAndNearMiss.test_saver_surplus_branch) ... ok
test_tag_bill_payer (tests.test_tags.PositiveAndNearMiss.test_tag_bill_payer) ... ok
test_tag_branch_reliant (tests.test_tags.PositiveAndNearMiss.test_tag_branch_reliant) ... ok
test_tag_business_income (tests.test_tags.PositiveAndNearMiss.test_tag_business_income) ... ok
test_tag_card_heavy_spender (tests.test_tags.PositiveAndNearMiss.test_tag_card_heavy_spender) ... ok
test_tag_cash_depositor (tests.test_tags.PositiveAndNearMiss.test_tag_cash_depositor) ... ok
test_tag_digital_first (tests.test_tags.PositiveAndNearMiss.test_tag_digital_first) ... ok
test_tag_dormant (tests.test_tags.PositiveAndNearMiss.test_tag_dormant) ... ok
test_tag_established_customer (tests.test_tags.PositiveAndNearMiss.test_tag_established_customer) ... ok
test_tag_falling_income (tests.test_tags.PositiveAndNearMiss.test_tag_falling_income) ... ok
test_tag_foreign_currency_spender (tests.test_tags.PositiveAndNearMiss.test_tag_foreign_currency_spender) ... ok
test_tag_frequent_fee_payer (tests.test_tags.PositiveAndNearMiss.test_tag_frequent_fee_payer) ... ok
test_tag_frequent_traveller (tests.test_tags.PositiveAndNearMiss.test_tag_frequent_traveller) ... ok
test_tag_going_dormant (tests.test_tags.PositiveAndNearMiss.test_tag_going_dormant) ... ok
test_tag_high_cash_user (tests.test_tags.PositiveAndNearMiss.test_tag_high_cash_user) ... ok
test_tag_high_inflow (tests.test_tags.PositiveAndNearMiss.test_tag_high_inflow) ... ok
test_tag_insurance_payer (tests.test_tags.PositiveAndNearMiss.test_tag_insurance_payer) ... ok
test_tag_investor (tests.test_tags.PositiveAndNearMiss.test_tag_investor) ... ok
test_tag_irregular_income (tests.test_tags.PositiveAndNearMiss.test_tag_irregular_income) ... ok
test_tag_large_recent_inflow (tests.test_tags.PositiveAndNearMiss.test_tag_large_recent_inflow) ... ok
test_tag_loan_repayer (tests.test_tags.PositiveAndNearMiss.test_tag_loan_repayer) ... ok
test_tag_multi_source_income (tests.test_tags.PositiveAndNearMiss.test_tag_multi_source_income) ... ok
test_tag_new_customer (tests.test_tags.PositiveAndNearMiss.test_tag_new_customer) ... ok
test_tag_online_shopper (tests.test_tags.PositiveAndNearMiss.test_tag_online_shopper) ... ok
test_tag_p2p_transfer_active (tests.test_tags.PositiveAndNearMiss.test_tag_p2p_transfer_active) ... ok
test_tag_re_engaged (tests.test_tags.PositiveAndNearMiss.test_tag_re_engaged) ... ok
test_tag_remittance_receiver (tests.test_tags.PositiveAndNearMiss.test_tag_remittance_receiver) ... ok
test_tag_remittance_sender (tests.test_tags.PositiveAndNearMiss.test_tag_remittance_sender) ... ok
test_tag_rent_payer (tests.test_tags.PositiveAndNearMiss.test_tag_rent_payer) ... ok
test_tag_rising_income (tests.test_tags.PositiveAndNearMiss.test_tag_rising_income) ... ok
test_tag_salary_earner (tests.test_tags.PositiveAndNearMiss.test_tag_salary_earner) ... ok
test_tag_saver (tests.test_tags.PositiveAndNearMiss.test_tag_saver) ... ok
test_tag_spending_exceeds_inflow (tests.test_tags.PositiveAndNearMiss.test_tag_spending_exceeds_inflow) ... ok
test_tag_subscription_user (tests.test_tags.PositiveAndNearMiss.test_tag_subscription_user) ... ok
test_age_field_is_refused_with_the_policy_note (tests.test_taxonomy.Fairness.test_age_field_is_refused_with_the_policy_note) ... ok
test_fairness_block_documents_exclusions (tests.test_taxonomy.Fairness.test_fairness_block_documents_exclusions) ... ok
test_no_tag_text_mentions_a_protected_trait_or_age (tests.test_taxonomy.Fairness.test_no_tag_text_mentions_a_protected_trait_or_age) ... ok
test_protected_distinct_field_is_refused (tests.test_taxonomy.Fairness.test_protected_distinct_field_is_refused) ... ok
test_protected_trait_filter_is_refused (tests.test_taxonomy.Fairness.test_protected_trait_filter_is_refused) ... ok
test_proxy_category_cannot_select_transactions (tests.test_taxonomy.Fairness.test_proxy_category_cannot_select_transactions) ... ok
test_proxy_category_may_be_excluded (tests.test_taxonomy.Fairness.test_proxy_category_may_be_excluded) ... ok
test_changing_a_threshold_in_the_json_changes_the_result (tests.test_taxonomy.RulesComeFromTheFile.test_changing_a_threshold_in_the_json_changes_the_result) ... ok
test_rates_are_read_from_the_settings (tests.test_taxonomy.RulesComeFromTheFile.test_rates_are_read_from_the_settings) ... ok
test_removing_a_tag_from_the_json_removes_it (tests.test_taxonomy.RulesComeFromTheFile.test_removing_a_tag_from_the_json_removes_it) ... ok
test_between_25_and_40_tags_with_unique_ids (tests.test_taxonomy.Shape.test_between_25_and_40_tags_with_unique_ids) ... ok
test_declared_fields_equal_the_fields_the_rule_reads (tests.test_taxonomy.Shape.test_declared_fields_equal_the_fields_the_rule_reads) ... ok
test_every_tag_has_the_required_parts (tests.test_taxonomy.Shape.test_every_tag_has_the_required_parts) ... ok
test_reason_windows_match_the_rule_windows (tests.test_taxonomy.Shape.test_reason_windows_match_the_rule_windows)
A reason saying 'last 6 months' must come from a 6-month window in that tag. ... ok
test_bad_window (tests.test_taxonomy.StrictValidation.test_bad_window) ... ok
test_declared_fields_must_match (tests.test_taxonomy.StrictValidation.test_declared_fields_must_match) ... ok
test_dependency_cycle_is_refused (tests.test_taxonomy.StrictValidation.test_dependency_cycle_is_refused) ... ok
test_duplicate_json_keys_are_refused (tests.test_taxonomy.StrictValidation.test_duplicate_json_keys_are_refused) ... ok
test_reason_placeholder_must_exist (tests.test_taxonomy.StrictValidation.test_reason_placeholder_must_exist) ... ok
test_threshold_must_be_a_number (tests.test_taxonomy.StrictValidation.test_threshold_must_be_a_number) ... ok
test_unknown_dependency_is_refused (tests.test_taxonomy.StrictValidation.test_unknown_dependency_is_refused) ... ok
test_unknown_key (tests.test_taxonomy.StrictValidation.test_unknown_key) ... ok
test_unknown_metric (tests.test_taxonomy.StrictValidation.test_unknown_metric) ... ok
test_unknown_op (tests.test_taxonomy.StrictValidation.test_unknown_op) ... ok

----------------------------------------------------------------------
Ran 117 tests in 7.556s

OK
```
