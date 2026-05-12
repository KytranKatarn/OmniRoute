"""
Encode / decode / parse the LDAP-style distinguished names used by GEDS-SAGE.

Format: OU=<acronym>[,OU=<parent>...],O=GC,C=CA
URL form: base64-encoded DN passed as ?dn=<b64>.
"""

import base64
from typing import Dict, List, Union


class DnParseError(ValueError):
    pass


def encode_dn(dn: str) -> str:
    return base64.b64encode(dn.encode("ascii")).decode("ascii")


def decode_dn(b64: str) -> str:
    try:
        return base64.b64decode(b64, validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as e:
        raise DnParseError(f"invalid DN b64 {b64!r}: {e}") from e


def parse_dn(dn: str) -> Dict[str, Union[str, List[str]]]:
    """
    Parse 'OU=Branch,OU=Dept,O=GC,C=CA' into:
      {'OU': ['Branch', 'Dept'], 'O': 'GC', 'C': 'CA'}
    """
    out: Dict[str, Union[str, List[str]]] = {"OU": []}
    for part in dn.split(","):
        if "=" not in part:
            raise DnParseError(f"malformed DN component: {part!r}")
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "OU":
            out["OU"].append(v)
        else:
            out[k] = v
    if "O" not in out or "C" not in out:
        raise DnParseError(f"DN missing required O/C: {dn!r}")
    return out
