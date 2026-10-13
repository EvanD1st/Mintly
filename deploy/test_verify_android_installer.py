import base64,hashlib,importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('verify_installer',Path(__file__).with_name('verify-android-installer.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class CertificateChecks(unittest.TestCase):
    def test_der_and_pem_represent_the_same_certificate(self):
        with tempfile.TemporaryDirectory() as root:
            der=b'example certificate bytes';path=Path(root)/'cert'
            path.write_bytes(der);expected=module.certificate_hash(path)
            path.write_bytes(b'-----BEGIN CERTIFICATE-----\n'+base64.b64encode(der)+b'\n-----END CERTIFICATE-----\n')
            self.assertEqual(expected,module.certificate_hash(path))
    def test_sdk_labels_case_and_whitespace_preserve_the_signer_identity(self):
        digest='ab'*32
        for label in ('Signer #1','Signer (minSdkVersion=24, maxSdkVersion=2147483647)'):
            self.assertEqual(module.signer_hashes(label+' certificate SHA-256 digest:  '+digest.upper()+'\r\n'),{digest})
    def test_stamp_and_public_key_hashes_cannot_substitute_for_signers(self):
        self.assertEqual(module.signer_hashes('Source Stamp Signer certificate SHA-256 digest: '+'ab'*32+'\nSigner #1 public key SHA-256 digest: '+'ab'*32),set())
    def test_different_signers_remain_distinguishable(self):
        self.assertEqual(module.signer_hashes('Signer #1 certificate SHA-256 digest: '+'ab'*32+'\nSigner #2 certificate SHA-256 digest: '+'cd'*32),{'ab'*32,'cd'*32})
