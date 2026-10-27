"""El cifrado de las contraseñas de las cuentas.

La base de datos guarda contraseñas de correo. En claro en un fichero, se
leen con un ``cat`` y acaban en cualquier copia de seguridad sin
protección. Aquí se cifran con una clave que **no está en la base de
datos**: la variable ``MCP_DASHBOARD_KEY``.

El algoritmo es AES-GCM con un nonce aleatorio por contraseña. La clave
sale de la del operador con HKDF, para que un mismo passphrase sirva para
varias bases sin que una sepase de la otra.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: Sal fija: no hace falta que sea secreta, y hace que la misma clave
#: deriving siempre la misma clave de cifrado.
SALT = b"mcp-correo-cuentas-v1"
#: Longitud mínima de la clave del operador.
MIN_KEY_LENGTH = 16
#: Nonce de AES-GCM.
NONCE_LENGTH = 12


class CipherError(Exception):
    """No se pudo cifrar o descifrar. El mensaje no lleva el secreto."""


class Cipher:
    """Cifra y descifra las contraseñas de las cuentas."""

    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or len(key.strip()) < MIN_KEY_LENGTH:
            raise CipherError(
                f"La clave del panel es demasiado corta (mínimo {MIN_KEY_LENGTH} caracteres)."
            )
        self._key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=SALT,
            info=b"mcp-correo-panel-cuentas",
        ).derive(key.strip().encode("utf-8"))
        self._aead = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> bytes:
        """Cifra un texto. El nonce va delante, en claro."""
        nonce = os.urandom(NONCE_LENGTH)
        try:
            return nonce + self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)
        except Exception as exc:  # pragma: no cover - no debería pasar
            raise CipherError("No se pudo cifrar la contraseña.") from exc

    def decrypt(self, blob: bytes) -> str:
        """Descifra. Si la clave no es la de este texto, lo dice."""
        if not isinstance(blob, (bytes, bytearray)) or len(blob) <= NONCE_LENGTH:
            raise CipherError("La contraseña guardada está dañada.")
        nonce = bytes(blob[:NONCE_LENGTH])
        try:
            return self._aead.decrypt(nonce, bytes(blob[NONCE_LENGTH:]), None).decode("utf-8")
        except InvalidTag:
            raise CipherError(
                "La contraseña guardada no se puede descifrar: la clave no es la de esta base."
            ) from None
        except Exception:
            raise CipherError("La contraseña guardada está dañada.") from None
