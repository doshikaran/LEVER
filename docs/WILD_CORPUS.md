# Wild Three corpus

Curated generality / honesty fixtures for judge demos and hit-rate measurement.

| ID | Source | Expected outcome |
|---|---|---|
| **W1** | `fixtures/wild_synth/` (unregistered `scale`) | Verified via generative harness (medium/high when e2b+keys available); otherwise unit-path harness IR still builds |
| **W2** | `fixtures/hero2/` via demo chip | Verified throughput / retry-storm Arena (retry loop visible in Search fog) |
| **W3** | `interface/tests/fixtures/degradation/unscopable/` | Degradation+ showcase (live framework object → manual recipe, no toy) |

Optional live PR (when `GITHUB_TOKEN` / public network available): paste any small pure-Python PR after W1.

## Hit rate

Run:

```bash
cd lever && source .venv/bin/activate
python scripts/run_wild_corpus.py
```

The script prints a table. Update the README **Live hit-rate** line with the `verified` fraction from a cold machine before demos.

## Notes

- W1 proves Phase B generality (not in `ENTRY_POINT_REGISTRY`).
- W2 proves game stage + fog under a known hero.
- W3 proves trust: Lever refuses instead of faking a microworld.
