"""Allow running CLI as `python -m hemm.cli`."""

from hemm_core.cli import main

raise SystemExit(main())
