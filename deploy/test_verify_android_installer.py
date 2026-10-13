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
