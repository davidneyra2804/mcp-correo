"""Acceso IMAP. La lectura no muta el buzón; la escritura vive en mail.mutate."""

from mail.imap import MailService

__all__ = ["MailService"]
