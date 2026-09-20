"""A contender must never write metadata before acquiring the endpoint lock."""
import pytest

from iris_gateway.link import EndpointLock


def test_contender_during_owner_metadata_replacement(tmp_path):
    endpoint = "project-start:metadata-race"
    owner = EndpointLock(endpoint, root=tmp_path)
    contender = None
    try:
        owner.acquire()
        # Pause at the real acquire() window between truncate and metadata write.
        owner._file.seek(0)
        owner._file.truncate()
        owner._file.flush()
        contender = EndpointLock(endpoint, root=tmp_path)
        assert owner.path.stat().st_size == 0
        assert EndpointLock.held(endpoint, tmp_path)
        with pytest.raises(RuntimeError, match="owned by another"):
            contender.acquire()
        owner.close()
        contender.acquire()
        contender._file.seek(0)
        assert b"pid=" in contender._file.read()
    finally:
        owner.close()
        if contender is not None:
            contender.close()
