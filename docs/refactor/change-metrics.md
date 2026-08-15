# Refactor change metrics

Final metrics are computed against
`332abc4f4a3e6d1bf61cec87b48d4a995c9657f7` after qualification.

| Metric | Final value |
|---|---:|
| Files changed | 55 |
| Production LOC added / removed | 5,149 / 4,541 |
| Test LOC added / removed | 241 / 0 |
| Documentation LOC added / removed | 488 / 5 |
| Modules split or introduced | 31 new focused Python modules, including package markers |
| Duplicated definitions eliminated | 4 implementation families |
| Proven dead helpers removed | 18 |
| Compatibility facades retained | 5 |
| Import cycles removed | 1 |

Most production additions are moved implementation, explicit adapter/service
boundaries, and typed page composition rather than new behavior. The four
consolidated implementation families are FASTQ discovery/pairing, analysis and
protocol policy, run identity/metadata persistence, and Snakemake command and
process control.
