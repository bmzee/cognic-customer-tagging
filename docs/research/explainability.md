# Explaining tags to staff

Relationship managers will ask why a customer has a tag and why they do not have another one. This note looks at what research, standards bodies and regulators say about explaining automated outputs, and turns that into a design for the tag card and the assistant's answers. An explanation that is vague, incomplete or different from what the engine did misleads staff even when the tag is correct.

## Findings

### Kinds of explanation

- Explanations can be global (how the system behaves for everyone) or local (why this output for this case). A system can be self-interpretable, where the model is the explanation, or explained afterwards by a second tool such as feature-importance or counterfactual search ([Four Principles of Explainable AI](https://nvlpubs.nist.gov/nistpubs/ir/2021/NIST.IR.8312.pdf)).
- An after-the-fact explanation of an opaque model cannot be fully faithful: if it matched the model exactly, it would be the model. A stand-in can reproduce predictions using different features, so its reasons can be wrong. For high-stakes uses an inherently interpretable model is the better choice, and on structured data it often costs no accuracy ([Stop Explaining Black Box Models](https://arxiv.org/abs/1811.10154)).
- In this plugin the declarative rule is the model. Evaluating it for one customer is the local explanation; the taxonomy in words is the global one. Nothing needs approximating.

### Contrastive and counterfactual explanations

- People rarely ask why something happened in isolation. They ask why it happened instead of something else, expect one or two selected causes, and prefer causes to probabilities ([Explanation in Artificial Intelligence](https://arxiv.org/abs/1706.07269)). "Why not salary earner?" is that kind of question.
- A counterfactual states the smallest change that would have produced a different outcome. It aims to help a person understand, contest and see what would need to differ. Several varied counterfactuals often help more than one, since the nearest may involve something fixed ([Counterfactual Explanations without Opening the Black Box](https://arxiv.org/abs/1711.00399)).
- Many valid counterfactuals usually exist and can conflict, so a generator must choose which to show ([Interpretable Machine Learning: Counterfactual Explanations](https://christophm.github.io/interpretable-ml-book/counterfactual.html)).
- Further pitfalls ([Hidden Assumptions Behind Counterfactual Explanations](https://arxiv.org/abs/1912.04930)): feature changes do not map cleanly to real actions; features move together; time-based features cannot be changed at will; which change counts as smallest depends on an arbitrary scaling between features; and showing only what is easy to change can hide that a result turned on something fixed.
- Small declarative rules avoid most of this: every unmet condition can be listed with its value and threshold, with no search or selection.

### Regulatory expectations

- Data-protection guidance on automated decisions asks for simple accounts of the rationale or criteria. The full algorithm is not required, but the reasons must be understandable. Human review counts only if the reviewer has the authority and competence to change the outcome ([Guidelines on Automated Decision-Making and Profiling](https://ec.europa.eu/newsroom/article29/items/612053)).
- A 2025 ruling on the right of access held that information about the logic of an automated decision means the procedure and principles actually applied, in concise and intelligible form. A complex formula is not enough; showing how different input data would have changed the result can help ([Case C-203/22](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62022CJ0203)).
- Adverse-action reason statements in consumer credit are a useful benchmark for wording ([Circular 2022-03](https://www.consumerfinance.gov/compliance/circulars/circular-2022-03-adverse-action-notification-requirements-in-connection-with-credit-decisions-based-on-complex-algorithms/); [official interpretation of the notification rule](https://www.consumerfinance.gov/rules-policy/regulations/1002/interp-9/)). Good reasons are specific, accurate and name the factors actually used. Bad reasons point to internal standards or a missed qualifying score without naming the factor, or pick the nearest checklist item when it was not the real reason. Model complexity is no excuse. The same commentary lets a reason name a factor without its direction or size and treats four reasons as a practical limit, which keeps such statements vague (Hidden Assumptions).
- Human-oversight rules for high-risk AI systems require that overseers can interpret outputs, can disregard or override them, and stay aware of automation bias ([AI Act Article 14](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14)).
- These regimes cover decisions with significant effect. The plugin is outside them by design (credit, pricing, fraud and AML uses are prohibited), so we use them as a quality bar; the bank's regulator and data-protection law set the actual obligations.

### Human factors

- Why something happened is easier to follow than why it did not. A system should say when a question is outside its design or the data is not enough, rather than answer anyway (Four Principles).
- Use plain, short language for the audience, and say how a human can review the output and who to contact ([Explaining decisions made with AI](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/explaining-decisions-made-with-artificial-intelligence/part-1-the-basics-of-explaining-ai/what-goes-into-an-explanation/)). Its advice to show uncertainty translates here into data completeness (missing fields, partial windows), not confidence levels.
- Explanations can raise trust without raising correctness: in controlled studies they made people more likely to accept a recommendation whether it was right or wrong ([Does the Whole Exceed its Parts?](https://arxiv.org/abs/2006.14779)).
- More detail is not automatically better. People shown a fully transparent model with many features were worse at spotting its large mistakes, apparently from information overload ([Manipulating and Measuring Model Interpretability](https://arxiv.org/abs/1802.07810)).

### Explanation fidelity

- Explanation accuracy is separate from decision accuracy: a correct tag can come with a wrong explanation (Four Principles). A separate explanation layer drifts from what decided (Stop Explaining Black Box Models), and the credit circular requires reasons to match the factors actually used.
- Step-by-step reasoning written by large language models can sound plausible while misstating what drove the answer ([Language Models Don't Always Say What They Think](https://arxiv.org/abs/2305.04388)). The assistant must pass on reasons the engine computed, never rebuild them.

## Design decisions for this plugin

1. **One trace, many views.** For each customer and tag the engine writes one evaluation trace: rule and taxonomy versions, as-of date, data window, and per condition the measure, actual value, comparator, threshold and result, plus the evidence that counted and data notes. Card, assistant and audit log all render from it; no other code produces reasons.
2. **Generated rule text.** The rule in words comes from the JSON rule via a template, never by hand, so wording cannot drift from logic.
3. **Tag card fields**, in order: tag name and status (tagged, not tagged, not evaluated); rule in words; conditions table (measure, actual value with unit, threshold, result); evidence that counted, such as the months with a salary credit; as-of date and data window as absolute dates; data notes (missing fields, partial months, excluded transactions); rule and taxonomy version; intended use (service and personalisation) and prohibited uses (credit, pricing, fraud or AML decisions, automated decisions with significant effect). No score, rank or probability anywhere.
4. **"Why" answer:** one-line result naming the rule; rule in words; every condition as "measure: value, needs threshold — met"; as-of date and window; data notes; one line on intended use.
5. **"Why not" answer:** every unmet and not-evaluated condition with actual value, threshold and gap, and every branch of rules with alternatives. Never pick a closest route. State the gap as a fact about the data ("salary months: 4, needs at least 6 — not met") and note that time-window conditions are rechecked as the window moves. Never phrase it as advice to the customer.
6. **Not evaluated is its own state.** Name the missing field and stop. Do not estimate, infer, or show it as not met.
7. **Avoid overload.** The first view shows the result and the full conditions table; long evidence lists (individual months or transactions) are one click or one follow-up away.
8. **Assistant phrasing rules:**
   - Answer only from tool output; if the tool fails or returns nothing, say so.
   - Copy numbers, units, thresholds and dates exactly; never round them.
   - Make the rule the subject: "meets the saver rule", not "is a saver". No claims about character, intent or circumstances.
   - No likelihoods, scores or hedges like "probably", and no reason the trace lacks.
   - Decline prohibited uses and say why.
   - Use the taxonomy's names for tags and measures every time.
   - Remind staff that a tag describes recorded transactions, can be wrong, and can be challenged.
9. **Fidelity tests.** Golden tests check that every number and condition in sample answers equals the trace, and that card and answer agree for the same customer and as-of date.
10. **Feedback route.** Staff can flag a tag as wrong from the card; flags reach rule owners, so review has real effect.

## What we adopt, what we reject, and why

- **Adopt:** declarative rules as the model. The only fully faithful explanation is the model itself.
- **Adopt:** a conditions table with value, threshold and result. Specific, accurate reasons naming the factors used are the bar regulators set.
- **Adopt:** contrastive "why not" answers from unmet conditions. Staff questions are contrastive, and small rules make listing every gap cheap.
- **Adopt:** "not evaluated" with the missing field. It follows the knowledge-limits principle and avoids guessing.
- **Adopt:** one trace for card, assistant and audit. Fidelity should hold by construction, not by review.
- **Reject:** after-the-fact attribution such as feature-importance or stand-in models. There is no opaque model to explain, and they add a second, less faithful account.
- **Reject:** reasons composed freely by the assistant. Generated reasoning can be plausible and unfaithful.
- **Reject:** a cap on the number of reasons. Our rules are small, and truncation is where biased selection creeps in.
- **Reject:** closest-counterfactual advice. It needs arbitrary scaling, hides fixed factors, and turns a service tag into customer guidance.
- **Reject:** scores, confidence levels and vague codes. They invite over-trust and give staff nothing to check.
