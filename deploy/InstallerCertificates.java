import java.io.File;
import java.security.MessageDigest;
import java.util.HexFormat;
import com.android.apksig.ApkVerifier;

/** Stable SDK API verification; certificate identity never depends on CLI labels. */
class InstallerCertificates {
    public static void main(String[] args) throws Exception {
        ApkVerifier.Result result=new ApkVerifier.Builder(new File(args[0]))
            .setMinCheckedPlatformVersion(24).build().verify();
        if(!result.isVerified()) throw new SecurityException("Invalid APK signature: "+result.getErrors());
        StringBuilder output=new StringBuilder("[");
        for(var certificate:result.getSignerCertificates()) {
            if(output.length()>1)output.append(',');
            output.append('"').append(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(certificate.getEncoded()))).append('"');
        }
        System.out.println(output.append(']').toString());
    }
}
