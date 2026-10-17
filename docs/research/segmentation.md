# Behavioural segmentation

Retail customer analytics usually groups customers by how they transact, most often with RFM scores or clustering. This note asks which of those practices suit a plugin whose tags must be deterministic, readable and stable. It also asks how to add a few mutually exclusive groups, starting with engagement (active, going dormant, dormant), without losing those properties.

## Findings

### RFM and its variants

- RFM describes a customer by recency (time since the last transaction), frequency (how many transactions) and monetary value (average or total amount). Variants add tenure (LRFM), profit or volume. A review of 105 segmentation studies found that customers are mostly represented by hand-picked features or RFM, and that k-means is the default method whatever the data size ([Customer segmentation review](https://ideas.repec.org/a/spr/infsem/v21y2023i3d10.1007_s10257-023-00640-4.html)).
- Under a standard model of repeat buying, the three RFM numbers carry all the information in a purchase history, but the observed values are noisy and their link to future activity is strongly non-linear ([RFM and CLV](http://www.brucehardie.com/papers/rfm_clv_2005-02-16.pdf)). Two results matter here. After a long silence, a customer who used to transact often is more likely to have left than one who transacted rarely, so silence means more against a regular rhythm. And an average amount built from a few transactions is unreliable and drifts towards the mean.
- Common tools score each dimension 1 to 3 or 1 to 5, against fixed thresholds or against percentiles of the customer base, and map score combinations to named groups ([RFM scoring lesson](https://academy.klaviyo.com/en-us/courses/getting-started-with-marketing-analytics/lessons/rfm-analysis), [RFM report](https://help.klaviyo.com/hc/en-us/articles/18194102384539)). Percentile scores are relative: a customer's group can change because other customers changed. A combined cell such as "3-2-1" hides which behaviour drove the result.

### Rule-based versus clustering-based segmentation

- Clustering (k-means, hierarchical, latent class) finds groups in the data. A k-means assignment depends on every feature and on where the centres happened to land, so there is often no short reason why a customer sits in a cluster ([Explainable k-means](https://arxiv.org/abs/2002.12538)).
- The number of clusters has no ground truth. With the wrong k, runs on different samples split the data differently. Choosing k by stability works only for compact, centre-shaped clusters and small k, and a stable answer is not necessarily a correct one ([Clustering stability overview](https://arxiv.org/abs/1007.1075)).
- Latent class models give each customer a probability per segment; latent Markov variants let membership change over time. Marketing research separates a change in what a segment means from a change in who belongs to it ([Dynamic segmentation](https://www2.econ.osaka-u.ac.jp/econ_society/dp/0109satomura.pdf)). Both probabilities and drifting meaning are hard to explain to a relationship manager.
- Rule-based segments are thresholds on named features, set by people. They need judgement and can miss structure, but their meaning is fixed by definition and survives every re-run.

### Stability over time

- In a household panel of retail financial behaviour, segment sizes and profiles stayed roughly constant, yet 40 to 50% of households changed segment each year, rising over time ([As time goes by](https://research.hhs.se/esploro/outputs/other/As-time-goes-by/991001480507606056)). Stable totals can hide heavy individual movement.
- Refitting a clustering model moves boundaries and can relabel clusters, so re-segmenting also changes what each segment means.
- Product-analytics lifecycle charts define exclusive states (new, current, resurrected, dormant) from the current and previous interval only ([Lifecycle chart](https://amplitude.com/docs/analytics/charts/lifecycle/lifecycle-interpret)). A one-interval memory makes customers with an irregular rhythm flip between states.
- Monitoring systems solve the same flapping problem with two timers: a condition must hold for a minimum time before an alert fires, and the alert can stay active for a while after the condition clears ([Alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)). That is a minimum duration plus hysteresis.

### Making segments explainable

- Explainability can be added before, during or after clustering, as tree paths, flat rule sets, prototypes or short descriptions. There is usually a trade-off between readability and fit ([Interpretable clustering survey](https://arxiv.org/abs/2409.00743)).
- A threshold tree with k leaves can describe k clusters, each by at most k−1 single-feature tests. But an ordinary decision tree fitted to cluster labels can be arbitrarily worse than the clusters it describes, and some loss is unavoidable ([Explainable k-means](https://arxiv.org/abs/2002.12538)). A surrogate explains itself, not the original model.
- Prototypes (a centroid or a typical member) are intuitive, but a centroid is an average customer who does not exist, and a real exemplar exposes one person's data.
- Practitioners name segments by intent, such as "Win-back" or "At risk". Such names promise a prediction the definition never makes.

### Multi-label tags versus exclusive segments

- Exclusive groups give clean counts and month-to-month transitions; RFM tools keep a current and a previous group for this reason ([RFM report](https://help.klaviyo.com/hc/en-us/articles/18194102384539)).
- Audience builders work the other way. Each audience is a rule over events and traits with a time window, a profile can belong to many, membership is recomputed as time passes, and entry and exit are explicit events. Audiences can be built from other audiences ([Audiences overview](https://www.twilio.com/docs/segment/engage/audiences)). The plugin's tags already follow this model.

### Fairness

- European data-protection guidance, cited here as general principle only, treats placing people into categories as profiling. People may ask which segments they are in; profiling can infer sensitive traits such as health from ordinary data like shopping records; and credit eligibility is given as an example of a significant effect ([Profiling guidelines](https://ec.europa.eu/newsroom/article29/items/612053/en)).
- Clustering that never sees a protected attribute can still produce clusters dominated by one protected group, because ordinary features act as proxies. The published remedy needs the protected attribute as input ([Fair clustering through fairlets](https://arxiv.org/abs/1802.05733)), which this plugin must never hold.
- Neutral definitions can still give skewed outcomes once an optimiser decides who is reached: a study of a large advertising platform found delivery skewed by gender and race ([Discrimination through optimization](https://arxiv.org/abs/1904.02095)). How a group is used matters as much as how it is defined.

## Design decisions for this plugin

1. **Engagement is one exclusive group family.** Every customer gets exactly one of `new`, `dormant`, `going_dormant`, `active`, checked in that order; the first match wins. `new` (account under 3 months old) covers customers with too little history to judge.
2. **Recency as a readable rule over monthly buckets.** Starting values for the bank to review: `active` means customer-initiated activity in the current or one of the two previous calendar months; `going_dormant` means the last such activity was 3 to 5 months ago; `dormant` means 6 months or more. With no activity at all, the count starts at account opening.
3. **Frequency appears as evidence, not as a score.** Each group shows the last activity date and the prior rhythm, for example "active in 5 of the 6 months before the gap", so staff can see whether the silence is unusual for this customer. A separate tag can later flag a gap longer than any in the previous 12 months.
4. **Count only customer-initiated activity, across all channels.** Interest, fees and other bank-initiated postings are excluded with direction and category filters; otherwise nobody is ever dormant. Every channel counts, so the group cannot become a proxy for age or disability through channel preference.
5. **Hysteresis and minimum duration live in the taxonomy.** A group rule may declare an entry condition, a separate stay condition and a minimum number of months before exit is checked. Example: a `dormant` customer moves to `active` only after activity in 2 separate months within 3; a single transaction adds a `reactivated` tag instead. Group changes are recorded at month-end checkpoints, while evidence stays exact to the day.
6. **Absolute, versioned thresholds only.** No percentiles: a group depends only on the customer's own data and the taxonomy version, so any as-of date can be reproduced. A threshold change is a new taxonomy version.
7. **Names describe behaviour, and transitions are reported.** Labels restate the rule, never a value or a prediction. The reader can return from/to counts between month-ends so the bank can watch how often customers switch and tune thresholds.

## What we adopt, what we reject, and why

- **Adopt:** recency and frequency from RFM, as separate readable rules and evidence on monthly buckets. They are cheap in the standard library and each explains itself.
- **Adopt:** a small exclusive family with fixed precedence and a catch-all. Staff see one clear state, and transitions can be counted.
- **Adopt:** hysteresis and minimum duration. They stop customers with an irregular rhythm from changing group every month.
- **Adopt:** multi-label rule tags for everything else, including `reactivated`. Overlapping tags keep each fact separate and visible.
- **Adopt:** behaviour-based names and fixed, versioned thresholds. Meaning stays stable and auditable.
- **Reject:** k-means, hierarchical and latent class clustering in the runtime. Membership has no short reason, meaning shifts on every refit, and the runtime has no learned models.
- **Reject:** decision-tree surrogates over clusters. The tree can disagree with the clusters it claims to explain.
- **Reject:** combined RFM scores and score cells. They hide which behaviour drove the result and invite use as a customer ranking for pricing or credit.
- **Reject:** percentile scoring. A customer's group would move when other customers move.
- **Reject:** monetary value in the engagement family. Engagement is about activity; ranking by amount adds little for service and edges towards prohibited uses.
- **Reject:** predictive labels or probabilities such as churn risk. The plugin reports what happened, not what might happen.
- **Reject:** prototypes built from real customers. They would expose one customer's data to explain another's group.
- **Reject:** fairness-aware clustering. It needs the protected attributes the plugin must never use; fairness here comes from feature choice, all-channel counting and limits on use.
