"""Versión del servidor.

Fuente de verdad única. `pyproject.toml` la repite porque el formato lo
exige, y un test comprueba que las dos no se separen. La imagen la lleva
como etiqueta OCI.

El número sigue SemVer: MAJOR.MINOR.PATCH. MAJOR sube cuando se rompe
la compatibilidad (una tool cambia de nombre, una variable de entorno
deja de existir), MINOR cuando se añade algo, PATCH cuando se corrige.
"""

from __future__ import annotations

__version__ = "1.0.7"
