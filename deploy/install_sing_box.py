"""Instala el binario fijado y verificado durante la construcción Docker."""

import hashlib
import io
import tarfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "1.14.2"
SHA256 = "a684484d7477d1437282ee411f4d131d0340aaad60a7868841ebd5d87dd8a0c6"
filename = f"sing-box-{VERSION}-linux-amd64.tar.gz"
with urlopen(
    f"https://github.com/SagerNet/sing-box/releases/download/v{VERSION}/{filename}",
    timeout=120,
) as response:
    package = response.read()
if hashlib.sha256(package).hexdigest() != SHA256:
    raise RuntimeError("El binario del proxy no coincide con su checksum.")
with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as archive:
    executable = archive.extractfile(f"sing-box-{VERSION}-linux-amd64/sing-box")
    if executable is None:
        raise RuntimeError("Falta el binario del proxy.")
    target = Path("/usr/local/bin/sing-box")
    target.write_bytes(executable.read())
    target.chmod(0o755)
