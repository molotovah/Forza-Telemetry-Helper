# Examples

- `session.csv` — a synthetic 3-lap session in the `fth live --csv` format
  (generated from `fth.fixtures.make_packet`).
- `report.txt` — the output of `fth analyze session.csv`.

Try them without a game:

```sh
fth analyze examples/session.csv
fth dashboard examples/session.csv
```
