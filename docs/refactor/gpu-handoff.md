# Harako-GPU-RNAseq handoff map

This map identifies selectively reusable assets only. No GPU application,
repository, Nextflow workflow, or nf-core integration was created.

## PORT_AS_IS

- pure FASTQ filename parsing and pairing primitives;
- sample schema and structural validation;
- analysis eligibility and policy-versioned analysis plan;
- canonical serialization, plan ID, and approval hash;
- reference/provenance and artifact response schemas.

## PORT_AFTER_ADAPTATION

- reference registry and cache resolver;
- immutable run configuration and manifest concepts;
- report shell and self-contained-report checks;
- project/sample editor presentation components;
- validation and error presentation.

These assets embed current Harako paths, reference-cache assumptions, or
Streamlit state and therefore require a deliberate target-backend adapter.

## REIMPLEMENT_FOR_GPU_BACKEND

- workflow runner and Nextflow execution;
- nf-core parameter generation;
- GPU capability/driver doctor;
- BAM retention and alignment-centric artifact collection;
- Nextflow resume and execution metadata;
- GPU/backend-specific output discovery.

## DO_NOT_PORT

- Snakemake command construction and the current `workflow/Snakefile`;
- current direct-Salmon workflow rules;
- all-in-one CPU image assumptions;
- release-specific legacy compatibility code.

This classification is not a commitment to a GPU product and does not make
the current CPU workflow generic for hypothetical engines.
