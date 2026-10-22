# Decision Ripple

Decision Ripple helps a maintainer find documents worth reviewing after an explicit decision changes. It compares old and new decision records, searches a chosen local corpus, and explains why each candidate appeared.

In the demo, a sharing decision changes from guest invitations being allowed to requiring workspace-owner approval. A guide that cites the decision ID appears first as an explicit reference. A support article mentioning guest invitations appears as a lexical candidate. An unrelated renderer guide does not appear. The report shows the changed decision, located excerpts, matched terms, and the distinction between reference evidence and similarity.

The first release is a local deterministic CLI. It ranks candidate paragraphs and produces JSON or Markdown. It does not declare that a document is wrong, understand causal dependencies, or edit downstream documents. An explicit reference is stronger retrieval evidence, but still does not prove that its surrounding content must change.

Its value is a review queue with inspectable reasons and disclosed scan scope. A complete-looking impact graph would overstate what v0.1 can establish.

Validate against known decision changes in a small documentation set. Measure relevant documents recovered, missed documents, irrelevant candidates, and review effort. Candidate counts and similarity scores alone are not impact measurements.
