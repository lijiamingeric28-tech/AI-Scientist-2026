"""Build the portable runtime inputs from an independently pinned, fully verified Dot release."""
import argparse
import lzma
import hashlib
import json
import shutil
from pathlib import Path

from astroquery_ai.registry.service import RegistryService
from astroquery_ai.runtime.codec import canonical, loads


def build(source, destination, manifest_digest):
    if not (source / 'origin/registry-handoff.json').is_file() or (source / 'runtime-inputs.json.xz').exists():
        raise ValueError('Publication requires the full, original reviewed source tree')
    manifest = loads((source / 'manifest.json').read_bytes())
    if manifest['content_sha256'] != manifest_digest:
        raise ValueError('The installed science release does not match the supplied release pin')
    # Validation checks every source byte, approved rule and science receipt before publication.
    verified = RegistryService(source.parent, None).validate(source)
    if verified['manifest'] != manifest or 'candidate' not in verified:
        raise ValueError('A fully reviewed candidate release is required')
    candidate = dict(verified['candidate'])
    science = {k: v for k, v in candidate.pop('science').items() if k != 'by_ref'}
    payload = {'format': 'reviewed-runtime-inputs/1', 'candidate': candidate, 'science': science,
               'amendment': verified['consumer_amendment']}
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / 'runtime-inputs.json.xz'
    with lzma.open(archive, 'wb', preset=3) as stream:
        stream.write(canonical(payload))
    shutil.copyfile(source / 'manifest.json', destination / 'manifest.json')
    with archive.open('rb') as stream:
        archive_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    pin = {'release_id': manifest['release_id'], 'manifest_content_sha256': manifest_digest,
           'runtime_inputs_sha256': archive_digest,
           'verified_source_files': candidate['report']['verified_files']}
    (destination / 'release.json').write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
    return pin


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('verified_directory', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest-content-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.verified_directory, args.output, args.manifest_content_sha256), indent=2))
