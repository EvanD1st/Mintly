"""Validate an APK signature, stable signing identity, version and release manifest."""
import base64,hashlib,json,re,subprocess,sys
from pathlib import Path

def certificate_hash(path):
    data=Path(path).read_bytes()
    if b'-----BEGIN CERTIFICATE-----' in data:
        data=base64.b64decode(data.split(b'-----BEGIN CERTIFICATE-----',1)[1].split(b'-----END CERTIFICATE-----',1)[0])
    return hashlib.sha256(data).hexdigest()

def signer_hashes(output):
    return {match.group(1).replace(':','').lower() for line in output.splitlines()
        if (match:=re.match(r'^Signer.*?\bcertificate SHA-256 digest:\s*([a-fA-F0-9:]+)\s*$',line.strip(),re.I))}

def main():
    tools,cert,root,apk_dir,output=map(Path,sys.argv[1:])
    expected=certificate_hash(cert)
    installed=json.loads((root/'docs/guided-ux-release-2026-10-09.json').read_text())['native_installer']['certificate_sha256']
    version=re.search(r'^version:\s*(\S+)',(root/'mobile/pubspec.yaml').read_text(),re.M).group(1)
    name,code=version.split('+');reports=[]
    for apk in apk_dir.glob('*.apk'):
        signature=subprocess.check_output([str(tools/'apksigner'),'verify','--print-certs',str(apk)],text=True)
        actual=signer_hashes(signature)
        print(json.dumps({'configured_certificate':expected,'installed_certificate':installed,'apk_certificates':sorted(actual)}))
        assert actual=={expected} and expected==installed,'Installer signing identity differs'
        badging=subprocess.check_output([str(tools/'aapt'),'dump','badging',str(apk)],text=True)
        assert "name='com.mintly.mintly'" in badging.splitlines()[0]
        assert "versionCode='"+code+"'" in badging.splitlines()[0]
        assert "versionName='"+name+"'" in badging.splitlines()[0]
        manifest=subprocess.check_output([str(tools/'aapt'),'dump','xmltree',str(apk),'AndroidManifest.xml'],text=True)
        assert 'UnlockTestActivity' not in manifest,'Debug test activity shipped'
        assert not re.search(r'android:debuggable[^\n]*0xffffffff',manifest),'Installer is debuggable'
        reports.append({'file':apk.name,'version':version,'package':'com.mintly.mintly','certificate_sha256':expected,
            'signature_verified':True,'certificate_matches_installed':True,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()})
    assert reports,'Signed installer missing'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(reports,indent=2))
    print(json.dumps(reports))

if __name__=='__main__':main()
