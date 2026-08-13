# Site screenshot provenance

The GitHub Pages screenshots were captured from the actual Harako-RNAseq
Streamlit GUI at source commit `451c712` on 2026-08-13. The current source was
mounted into a compatible local Harako container and viewed with headless
Chromium at a 1440 × 900 viewport and 100% browser zoom. Both the English and
Japanese locales were captured.

The demonstration used empty FASTQ placeholders, so no FASTQ sequence records
or real biological data were used. The visible synthetic sample names were:

- `Demo_Control_1`
- `Demo_Control_2`
- `Demo_Treated_1`
- `Demo_Treated_2`

Conditions were explicitly assigned in the GUI: the two control samples were
assigned to `Control`, and the two treated samples were assigned to
`Treatment`. No condition inference is implied. Visible paths were limited to
the neutral container path `/input` and relative demonstration paths. No
private paths, personal or patient identifiers, credentials, or internal
infrastructure details were included.

The browser captures were converted to lossless WebP with Pillow at their
native 1440 × 900 resolution. Re-encoding omitted unnecessary image metadata.
The published files are:

- `gui-samples-en.webp`
- `gui-summary-en.webp`
- `gui-samples-ja.webp`
- `gui-summary-ja.webp`

These images show the current public-beta interface at the source commit above;
they are not claimed to be byte-identical to a previously published container.
