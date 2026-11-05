#!/usr/bin/env python3
"""Matriz de mutaciones: cada arreglo del cambio, revertido, debe romper un test.

El punto de este script es el de AGENTS.md: "un test que no puede fallar no
vigila nada". Para cada mutacion se aplica al arbol, se corre la suite y se
comprueba que ALGUN test falla. Si un test pasa con el arreglo quitado, ese
test no vigila lo que dice vigilar.

Cada mutacion es una funcion que recibe el texto del fichero y devuelve el
texto mutado. Si no encuentra lo que busca, lo dice y aborta: una mutacion
que no se aplica no vigila nada, y es peor que no tenerla.

Uso: python herramientas/mutaciones_token_efectivo.py [raiz]
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _sustituir(texto: str, antes: str, despues: str) -> str:
    """Sustituye una vez, o aborta si no aparece."""
    if antes not in texto:
        raise SystemExit(f"no se encuentra el texto a mutar:\n{antes}")
    return texto.replace(antes, despues, 1)


#: (nombre, fichero, mutacion)
MUTACIONES: list[tuple[str, str, Callable[[str], str]]] = [
    (
        "el token efectivo vuelve a ser solo el propio",
        "store/store.py",
        lambda t: _sustituir(
            t,
            """        dominio = self.dominio(cuenta.domain_id)
        if dominio is not None and dominio.bearer:
            return dominio.bearer, "dominio"
        return "", "general\"""",
            """        return "", "general\"""",
        ),
    ),
    (
        "el origen se equivoca al heredar",
        "store/store.py",
        lambda t: _sustituir(
            t,
            'return dominio.bearer, "dominio"',
            'return dominio.bearer, "general"',
        ),
    ),
    (
        "la lectura del panel no devuelve el token",
        "dashboard/api.py",
        lambda t: _sustituir(t, '"token": token,', '"token": "",'),
    ),
    (
        "la lectura del panel dice que siempre hay token",
        "dashboard/api.py",
        lambda t: _sustituir(t, '"has_token": bool(token),', '"has_token": True,'),
    ),
    (
        "el valor del token llega a la auditoria",
        "dashboard/api.py",
        lambda t: _sustituir(
            t,
            '{"origen": origen}',
            '{"origen": origen, "credencial": token}',
        ),
    ),
    (
        "el listado no dice de que credencial viene cada cuenta",
        "dashboard/api.py",
        lambda t: _sustituir(
            t,
            'publica["credential_source"] = origen',
            'publica["credential_source"] = "cuenta"',
        ),
    ),
    (
        "has_credential miente y dice que no hay credencial",
        "dashboard/api.py",
        lambda t: _sustituir(
            t,
            'publica["has_credential"] = origen != "general"',
            'publica["has_credential"] = bool(cuenta.bearer)',
        ),
    ),
    (
        "own_credential miente y dice que la credencial es propia",
        "dashboard/api.py",
        lambda t: _sustituir(
            t,
            'publica["own_credential"] = bool(cuenta.bearer)',
            'publica["own_credential"] = True',
        ),
    ),
    (
        "la ruta del panel no existe",
        "dashboard/app.py",
        lambda t: _sustituir(
            t,
            'Route("/api/accounts/{id}/credentials", api.credenciales_cuenta, methods=["GET"]),',
            'Route("/api/accounts/{id}/credenciales", api.credenciales_cuenta, methods=["GET"]),',
        ),
    ),
]


def _correr(raiz: Path) -> tuple[int, str]:
    proceso = subprocess.run(
        [str(raiz / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "--no-header"],
        cwd=raiz,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        timeout=900,
    )
    return proceso.returncode, (proceso.stdout or "") + (proceso.stderr or "")


def main() -> int:
    raiz = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else RAIZ
    if not (raiz / ".venv" / "bin" / "python").exists():
        print(f"No hay entorno en {raiz}.", file=sys.stderr)
        return 2

    original = {
        fichero: (raiz / fichero).read_text(encoding="utf-8") for _, fichero, _ in MUTACIONES
    }
    problemas: list[str] = []

    try:
        for descripcion, fichero, mutar in MUTACIONES:
            (raiz / fichero).write_text(original[fichero], encoding="utf-8")
            try:
                (raiz / fichero).write_text(mutar(original[fichero]), encoding="utf-8")
            except SystemExit as exc:
                problemas.append(f"{descripcion}: {exc}")
                print(f"NO APLICADA  {descripcion}  ({exc})")
                continue

            codigo, salida = _correr(raiz)
            if codigo == 0:
                problemas.append(f"{descripcion}: la suite sigue pasando. Ese test no vigila.")
                print(f"FALLA VIGILANCIA  {descripcion}")
            else:
                fallan = [linea for linea in salida.splitlines() if linea.startswith("FAILED")]
                resumen = fallan[0].replace("FAILED ", "").strip() if fallan else ""
                print(f"OK  {descripcion}  ->  {resumen[:110]}")
    finally:
        for fichero, texto in original.items():
            (raiz / fichero).write_text(texto, encoding="utf-8")

    print()
    if problemas:
        for problema in problemas:
            print("PROBLEMA:", problema)
        return 1
    print(f"Todas las mutaciones ({len(MUTACIONES)}) rompen la suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
