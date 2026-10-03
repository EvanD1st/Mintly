"""Small boundary checks that do not require a real wallet or a network."""
import os
import pytest
from fastapi import HTTPException
from app.config import settings
from app.services import automatic
from app.services.custody import private_read, private_write
from app.provision_custody import source_root


@pytest.mark.parametrize('chain',[1,8453,4663,42161,10,84532])
def test_mainnets_blocked_without_a_supported_explicit_opt_in(monkeypatch,chain):
    monkeypatch.setattr(settings,'ENABLE_CUSTODIAL_AUTOMATIC',True)
    monkeypatch.setattr(settings,'AUTOMATIC_CHAIN_ID',chain)
    monkeypatch.setattr(settings,'ENABLE_ROBINHOOD_AUTOMATIC',False)
    with pytest.raises(HTTPException,match='unsupported or Robinhood'):
        automatic.enabled()


def test_vault_files_are_exclusive_and_symlinks_are_rejected(tmp_path):
    path=tmp_path/'secret'
    private_write(path,'test-only-value')
    assert private_read(path)=='test-only-value'
    with pytest.raises(FileExistsError):
        private_write(path,'replacement')
    assert private_read(path)=='test-only-value'
    if os.name != 'nt':
        link=tmp_path/'link';link.symlink_to(path)
        with pytest.raises(ValueError):private_read(link)
        path.chmod(0o644)
        with pytest.raises(ValueError):private_read(path)


def test_provisioning_distinguishes_container_root_from_git_checkout(tmp_path):
    image = tmp_path/'image'
    image.mkdir()
    assert source_root(image/'app/provision_custody.py') == image
    checkout = tmp_path/'checkout'
    (checkout/'.git').mkdir(parents=True)
    assert source_root(checkout/'backend/app/provision_custody.py') == checkout
