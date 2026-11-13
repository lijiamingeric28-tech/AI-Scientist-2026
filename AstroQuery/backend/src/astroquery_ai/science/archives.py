"""Bounded official containers. No filesystem extraction or code execution."""

import base64
import gzip
import hashlib
import io
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from astroquery_ai.runtime.errors import DomainError

EXPANDED_LIMIT = 32 * 1024**2
MEMBER_LIMIT = 1024


def fits_manifest(raw):
    from astropy.io import fits
    with fits.open(io.BytesIO(raw), memmap=False) as file:
        return {'subject_headers':{k:str(file[0].header[k]) for k in
                ('OBJECT','NAME','TARGET','GAIA_DR3_SOURCE_ID') if k in file[0].header},
            'tables':[{'hdu':i,'name':hdu.name,'rows':hdu.header.get('NAXIS2',0),
                       'columns':[{'name':c.name,'unit':c.unit} for c in hdu.columns]}
                      for i,hdu in enumerate(file) if isinstance(hdu,(fits.BinTableHDU,fits.TableHDU))]}


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        return False
    parts = name.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts) or any(ord(char) < 32 for char in name):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *("com" + str(i) for i in range(1, 10)),
        *("lpt" + str(i) for i in range(1, 10)),
    }
    return all(
        part not in {".", ".."}
        and part.rstrip(" .") == part
        and part.split(".")[0].casefold() not in reserved
        for part in path.parts
    )


def archive_kind(name):
    lower = name.casefold()
    return (
        "zip"
        if lower.endswith(".zip")
        else "tar"
        if lower.endswith(".tar")
        else "gzip"
        if lower.endswith((".gz", ".tgz"))
        else None
    )


def structured_archive(path, *, original_filename):
    from .attachments import FORMATS

    path = Path(path)
    if path.stat().st_size > EXPANDED_LIMIT:
        raise DomainError("ARCHIVE_SIZE_LIMIT", "容器原件超过32MiB")
    raw = path.read_bytes()
    manifest, members, gaps = [], [], []
    expanded = 0

    def visit(data, name, chain, depth):
        nonlocal expanded
        kind = archive_kind(name)
        if depth > 2:
            gaps.append({"path": name, "reason": "archive_nesting_limit"})
            return
        records = []
        try:
            if kind == "zip":
                archive = zipfile.ZipFile(io.BytesIO(data))
                infos = archive.infolist()
                records = [
                    (
                        item.filename,
                        item.file_size,
                        item.is_dir(),
                        bool(item.flag_bits & 1),
                        stat.S_ISLNK(item.external_attr >> 16),
                        lambda item=item: archive.open(item),
                    )
                    for item in infos
                ]
            elif kind == "tar":
                archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
                infos = archive.getmembers()
                records = [
                    (
                        item.name,
                        item.size,
                        item.isdir(),
                        False,
                        not item.isfile() and not item.isdir(),
                        lambda item=item: archive.extractfile(item),
                    )
                    for item in infos
                ]
            elif kind == "gzip":
                archive = gzip.GzipFile(fileobj=io.BytesIO(data))
                child_name = name[:-4] + ".tar" if name.casefold().endswith(".tgz") else name[:-3]
                records = [(child_name, None, False, False, False, lambda: archive)]
            else:
                raise DomainError("ARCHIVE_FORMAT", "不支持的容器格式")
            seen = set()
            try:
                for member_name, size, directory, encrypted, link, opener in records:
                    if len(manifest) >= MEMBER_LIMIT:
                        gaps.append(
                            {
                                "path": name,
                                "reason": "archive_member_limit",
                                "remaining_members_not_inspected": True,
                            }
                        )
                        break
                    key = member_name.casefold()
                    entry = {
                        "path": member_name,
                        "parent_chain": chain,
                        "declared_bytes": size,
                        "sha256": None,
                        "state": "not_checked",
                    }
                    manifest.append(entry)
                    reason = (
                        "unsafe_member_path"
                        if not safe_name(member_name)
                        else "duplicate_member_name"
                        if key in seen
                        else "encrypted_member"
                        if encrypted
                        else "linked_or_special_member"
                        if link
                        else None
                    )
                    seen.add(key)
                    if reason:
                        entry.update(state="rejected", reason=reason)
                        gaps.append({"path": member_name, "reason": reason})
                        continue
                    if directory:
                        entry["state"] = "directory"
                        continue
                    if size is not None and size > EXPANDED_LIMIT - expanded:
                        entry.update(state="not_checked", reason="archive_expanded_byte_limit")
                        gaps.append({"path": member_name, "reason": "archive_expanded_byte_limit"})
                        break
                    try:
                        with opener() as source:
                            content = source.read(EXPANDED_LIMIT - expanded + 1)
                        if len(content) > EXPANDED_LIMIT - expanded:
                            entry.update(state="partial", reason="archive_expanded_byte_limit")
                            gaps.append(
                                {"path": member_name, "reason": "archive_expanded_byte_limit"}
                            )
                            break
                        expanded += len(content)
                        if size is not None and len(content) != size:
                            raise ValueError("member length mismatch")
                        sha = hashlib.sha256(content).hexdigest()
                        entry.update(state="hashed", actual_bytes=len(content), sha256=sha)
                        suffix = PurePosixPath(member_name).suffix.lower()
                        format = (
                            "readme"
                            if PurePosixPath(member_name).name.casefold() == "readme"
                            else FORMATS.get(suffix)
                        )
                        if content.startswith(b"%PDF-") or suffix == ".pdf":
                            if not content.startswith(b"%PDF-"):
                                entry.update(state='rejected', reason='invalid_pdf_member')
                                gaps.append({'path': member_name, 'reason': 'invalid_pdf_member'})
                                continue
                            format = 'pdf'
                        if archive_kind(member_name) and format != 'pdf':
                            entry.update(role="container")
                            child = {"path": member_name, "sha256": sha, "bytes": len(content)}
                            members.append(
                                {
                                    "path": member_name,
                                    "format": "container",
                                    "parent_chain": chain,
                                    "sha256": sha,
                                    "data_base64": base64.b64encode(content).decode("ascii"),
                                }
                            )
                            visit(content, member_name, [*chain, child], depth + 1)
                        elif format:
                            entry.update(
                                role={'readme': 'readme', 'pdf': 'supplementary_pdf'}.get(format, 'structured_candidate')
                            )
                            members.append(
                                {
                                    "path": member_name,
                                    "format": format,
                                    "parent_chain": chain,
                                    "sha256": sha,
                                    "data_base64": base64.b64encode(content).decode("ascii"),
                                    **({'fits_metadata':fits_manifest(content)} if format=='fits' else {}),
                                }
                            )
                        else:
                            entry["role"] = "unsupported_member_not_executed"
                    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
                        entry.update(state="partial", reason="member_read_failed")
                        gaps.append(
                            {
                                "path": member_name,
                                "reason": "member_read_failed",
                                "error_type": type(exc).__name__,
                            }
                        )
            finally:
                archive.close()
        except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
            gaps.append(
                {"path": name, "reason": "container_read_failed", "error_type": type(exc).__name__}
            )

    visit(raw, original_filename, [], 1)
    return {
        "schema_version": "OfficialContainerManifest/1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "original_filename": original_filename,
        "entries": manifest,
        "members": members,
        "gaps": gaps,
        "expanded_bytes": expanded,
        "member_limit": MEMBER_LIMIT,
        "expanded_limit": EXPANDED_LIMIT,
        "state": "partial" if gaps else "enumerated",
        "code_executed": False,
    }
