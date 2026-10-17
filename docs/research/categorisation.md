# Transaction categorisation and merchant normalisation

Many tags depend on knowing what a transaction was for: groceries, fuel, a utility bill, a salary. Raw bank data rarely says this cleanly, so the plugin must turn a noisy description or counterparty into a canonical merchant and a category. This note covers how that is done in practice, and how to do it while staying deterministic, explainable and clear of sensitive proxies.

## Findings

### What the raw data carries

- Descriptions are short, truncated and inconsistently formatted, and banks change the format without notice. Fragments can mislead, for example a payee's surname that matches a restaurant brand ([Making sense of messy data](https://plaid.com/blog/making-sense-of-messy-data/)).
- Open-banking account APIs carry no spending category. One standard offers a free-text narrative, an optional ISO 20022 bank transaction code, an optional issuer-defined code, and optional merchant details with an ISO 18245 code, the last behind a more detailed access permission ([Open Banking Read/Write API: Transactions](https://openbankinguk.github.io/read-write-api-site3/v3.1.10/resources-and-data-models/aisp/Transactions.html)).
- Another standard has a short transaction-type list (payment, direct debit, fee, interest, transfers in and out, other) and defines merchant name and code only for outgoing payments to a merchant ([Consumer Data Standards](https://consumerdatastandardsaustralia.github.io/standards/)).
- So a merchant code exists only for some card spending. Transfers, direct debits and fees need other signals.

### From raw text to a canonical counterparty

1. **Clean the text.** Fold case, collapse whitespace, and strip reference numbers, store numbers and dates, usually with regular expressions ([Scalable and Weakly Supervised Bank Transaction Classification](https://arxiv.org/abs/2305.18430)).
2. **Separate intermediaries from the real merchant.** One aggregator's API distinguishes merchants from marketplaces, payment terminals, transfer apps, financial institutions and income sources, and names a primary counterparty when several appear ([Enrich API reference](https://plaid.com/docs/api/products/enrich/)).
3. **Match to a known entity with a stable identifier.** When nothing matches, the same API returns the cleaned description as the name, in its lowest confidence band.

The hard part is merging spelling variants without merging distinct businesses: a ride-hailing service and its food-delivery arm share a brand but not a category. Hand-written patterns also break when a bank changes its format, which is why that aggregator moved to learned models ([Making sense of messy data](https://plaid.com/blog/making-sense-of-messy-data/)).

### Category schemes

- **ISO 18245** defines four-digit merchant category codes by line of business. It covers merchants expected to originate retail payments, does not require anyone to use the codes, and since 2023 is kept current by a maintenance agency ([ISO 18245](https://www.iso.org/standard/79450.html)). A code describes the merchant's trade, not what the customer bought.
- **ISO 20022 bank transaction codes** describe the kind of cash movement, not its purpose, in three levels: domain (such as payments), family (such as received credit transfers, card transactions or direct debits) and sub-family. Every domain has generic families for not available (`NTAV`) and other (`OTHR`), so the field stays honest when detail is missing. Banks may also send proprietary codes ([ISO 20022 Bank Transaction Codes](https://www.iso20022.org/sites/default/files/media/file/BTC_ExternalCodeListDescription_Nov2025.docx)).
- **Aggregator taxonomies** use a broad primary category and a finer intent-based one. Their owner versions them, and older transactions do not get later accuracy or confidence gains ([Personal Finance Category migration guide](https://plaid.com/docs/transactions/pfc-migration/)).

Neither code scheme is a spending category a relationship manager would recognise, so a mapping table is always needed.

### Rules versus learned classifiers

- **Accuracy.** Learned models cope with unseen, misspelled and truncated text better than exact rules ([Making sense of messy data](https://plaid.com/blog/making-sense-of-messy-data/)). Published numbers are modest. On small-business transactions with eleven categories, a fine-tuned transformer classifier scored about 73% overall and about 90% above a 0.8 confidence cut; a zero-shot large language model scored about 60%. Coverage above the cut was not reported, no rules baseline was tested, and explainability was left for later ([Categorising SME Bank Transactions](https://arxiv.org/abs/2508.05425)).
- **Rules underneath.** A weak-supervision system builds training labels from keyword anchors, regular expressions and spending patterns, then trains a network on them ([Scalable and Weakly Supervised Bank Transaction Classification](https://arxiv.org/abs/2305.18430)).
- **Drift and maintenance.** Learned systems build up hidden costs: entangled inputs, unstable data dependencies, undeclared consumers and sensitivity to outside change ([Hidden Technical Debt in Machine Learning Systems](https://papers.nips.cc/paper_files/paper/2015/hash/86df7dcfd896fcaf2674f757a2463eba-Abstract.html)). Rules drift too, but the fix is a visible table edit.
- **Explainability.** For consequential uses, an interpretable model beats an opaque one explained after the fact ([Stop Explaining Black Box Models](https://arxiv.org/abs/1811.10154)). A lookup row is its own explanation.

### Confidence and fallback

- Aggregators attach a confidence band to both category and counterparty. The top bands map to stated probability levels, and there is a separate unknown value ([Enrich API reference](https://plaid.com/docs/api/products/enrich/)).
- Raw scores from modern neural networks tend to be overconfident and need calibration before they mean what they say ([On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599)).
- A classifier can abstain, trading coverage for lower error, with the cut-off set to meet a target error rate ([Selective Classification for Deep Neural Networks](https://arxiv.org/abs/1705.08500)). The small-business study suggests routing low-confidence items, with the top two candidates, to a human reviewer.
- ISO 20022 builds the fallback in, with explicit not-available and other codes rather than a forced guess.

### Sensitive categories as proxies

- Guidance from one group of data-protection regulators says a single payment can reveal special-category data: a donation to a party or a place of worship, a union fee, a bill from a medical specialist. Profiling many transactions can create such data by inference. Where no legal exception applies, it points to technical measures that stop those data points being processed at all ([EDPB Guidelines 06/2020](https://www.edpb.europa.eu/system/files/documents/files/file1/edpb_guidelines_202006_psd2_afterpublicconsultation_en.pdf)).
- The same guidance says data about the other party to a payment must not be reused for unrelated purposes.
- Work on transaction data reports that purchase histories have been used to predict fields such as gender and marital status ([Fusing Multifaceted Transaction Data](https://arxiv.org/abs/1712.07230)). The category list is therefore a fairness control, not only a convenience.

## Design decisions for this plugin

1. **Two synthetic JSON tables.** A counterparty normalisation table and an ISO 18245-style code table; the real ISO list is sold by ISO and is not reproduced. The draft tables in `taxonomy/` already use `match` (`exact`, `prefix`, `contains`), `pattern`, `counterparty` and `kind`, and a `category` and `label` per code. Keep those names and add a `restricted` flag per category.
2. **Fixed normalisation.** An ordered, documented list of pure string steps: Unicode normalisation, case fold, whitespace collapse, removal of digit runs and dates, removal of intermediary prefixes listed in the table. Store raw text and normalised key together so any match can be replayed.
3. **Fixed matching order; first match wins.** Counterparty table first (exact, then prefix, then contains, longest pattern first, ties broken by a stated stable key), then merchant code via the code table, then bank transaction code family (transfers, fees, cash), then `uncategorised`. When the table and the merchant code disagree, the table wins and the evidence shows both.
4. **Confidence is provenance, not a score.** Each transaction carries `match_basis` from a closed list: `exact`, `prefix`, `contains`, `mcc`, `btc_family`, `uncategorised`. A tag rule may require a minimum basis. Tag evidence names the basis and the table version.
5. **Uncategorised is a real category.** Feature buckets count uncategorised spend. A tag that filters on category shows coverage in its evidence (for example, 92% of spend categorised) and abstains when the uncategorised share passes a threshold set in the taxonomy.
6. **Restricted categories collapse at ingest.** Healthcare, worship and religious bodies, charity, childcare and schools, political bodies, trade unions, dating, and government benefits by type are flagged `restricted`. The draft code table keeps them as named categories the engine refuses to select on; go further, and have the builder map them to one opaque `restricted` bucket with no per-category features. The taxonomy validator rejects any rule that filters on them, and the tool server never returns them. Remittance counterparty country and corridor are dropped at ingest.
7. **Private individuals are not named.** For a `person` counterparty the store keeps only the kind, not the cleaned name or an account number.
8. **Versioned tables, full replay.** Each table carries a version and content hash, and each feature bucket records the versions it used. A table change triggers a deterministic rebuild from the change feed, so no profile mixes versions.

## What we adopt, what we reject, and why

- **Adopt:** lookup tables with a fixed matching order. They are deterministic and replayable, and each match explains itself.
- **Adopt:** ISO 18245-style codes as one input, ranked below the counterparty table. They are common on card spending but describe the merchant's trade, not the purchase.
- **Adopt:** ISO 20022 domain, family and sub-family as the fallback for non-card movements. They are the only structured signal on transfers, fees and cash, with explicit not-available values.
- **Adopt:** a provenance field instead of a confidence score. It says how a category was reached without inventing a probability, and fits the no-scores rule.
- **Adopt:** collapsing restricted categories at ingest. Data never stored cannot leak into a tag, an answer or a later rule.
- **Reject:** learned classifiers and large language models at runtime. Their accuracy gains are real, but calibration, drift and explanation costs break the plugin's contract. An offline tool proposing table rows for human review is out of scope for now.
- **Reject:** fuzzy string similarity at runtime. Wrong merges are silent, and results shift as the table grows.
- **Reject:** adopting an aggregator's taxonomy wholesale. Its owner versions it, history misses later fixes, and it includes categories the plugin must not hold.
- **Reject:** editing tables in place without replay. Mixed versions would make tag evidence impossible to reproduce.
