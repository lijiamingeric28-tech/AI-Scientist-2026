import asyncio
import sys

import pytest

from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.parsing import Parsers


@pytest.mark.parametrize('output', ['', 'not-json'])
def test_parser_crash_or_corrupt_pipe_is_a_bounded_technical_failure(tmp_path, monkeypatch, output):
    path = tmp_path / 'SYNTHETIC-original.pdf'
    path.write_bytes(b'SYNTHETIC original remains available')
    spawn = asyncio.create_subprocess_exec
    observed = []

    async def failed_child(*args, **kwargs):
        observed.append({name: kwargs['env'][name] for name in
            ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
        return await spawn(sys.executable, '-c', 'import sys; sys.stdin.buffer.read(); sys.stdout.write(' + repr(output) + '); sys.exit(7)', **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', failed_child)
    monkeypatch.setenv('OPENBLAS_NUM_THREADS', '64')

    async def run():
        with pytest.raises(DomainError) as caught:
            await Parsers().run('inspect_pdf', path, timeout=5)
        assert caught.value.code == 'PARSER_FAILED' and caught.value.details['process_exit_code'] == 7
    asyncio.run(run())
    assert observed and all(value == '1' for value in observed[0].values())
    assert path.read_bytes() == b'SYNTHETIC original remains available'
