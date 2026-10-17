# Cognic customer tagging

A plugin for Cognic that tags customers from their transactions and profile. Every tag is explained by the rule and the evidence that produced it.

**Status:** stage 1 is in progress:
- the tag taxonomy and rules as data;
- a deterministic rules engine;
- synthetic test data and tests;
- a draft Cognic safety file.

Later stages (scheduled runs, then real-time profiles) follow when Cognic's plugin hosting is available.

## Rules this plugin follows
- **Synthetic data only** in this repository. No real customer data, and no bank names, hosts or logins.
- **Behaviour, not protected traits.** Tags never use religion, ethnicity, gender, disability or marital status. Age is excluded by default.
- **Explainable.** Every tag shows the rule and the evidence behind it.
- **Read-only.** The plugin never changes data.

## Licence
All rights reserved; see `LICENSE`. This repository is public for visibility and CI only; no licence to use the code is granted.
