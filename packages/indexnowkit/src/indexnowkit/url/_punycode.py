"""IDN host to ASCII through the ``idna`` codec of the standard library (RFC 3490 / nameprep: lower-cases and
punycode-encodes every non-ASCII label). The PHP family uses UTS #46 when ext-intl is there; the two agree on every
host of the conformance suite (Cyrillic, Latin with diacritics) and differ only on the deviation characters of UTS #46
(``ß``, ``ς``, ZWJ/ZWNJ), where IDNA 2003 maps ``ß`` to ``ss``.

Input is bounded (host <= 253 characters, label <= 63 code points) so nothing here is expensive.
"""

from __future__ import annotations

from indexnowkit.exceptions import InvalidUrlError

__all__ = ["encode_host"]

MAX_HOST_LENGTH = 253
MAX_LABEL_LENGTH = 63


def encode_host(host: str) -> str:
    """The ASCII (punycode) form of a host, unchanged when it is ASCII already.

    :raises InvalidUrlError: when a label cannot be encoded or is too long
    """
    if host.isascii():
        return host
    if len(host) > 4 * MAX_HOST_LENGTH:
        raise InvalidUrlError(f"Host name longer than {MAX_HOST_LENGTH} characters.")
    labels = []
    for label in host.lower().split("."):
        if label.isascii():
            labels.append(label)
            continue
        if len(label) > MAX_LABEL_LENGTH:
            raise InvalidUrlError(f"Host label longer than {MAX_LABEL_LENGTH} characters.")
        try:
            labels.append(label.encode("idna").decode("ascii"))
        except UnicodeError as error:
            raise InvalidUrlError(f'Host name "{host}" is not a valid IDN.') from error
    return ".".join(labels)
