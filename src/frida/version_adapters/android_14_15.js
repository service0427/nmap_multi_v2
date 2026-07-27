console.log("[*] Conscrypt APEX Adapter (Android 14/15) Loaded");

if (Java.available) {
    Java.perform(function() {
        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function(untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                console.log("[*] Android 14/15 conscrypt verifyChain bypass for host: " + host);
                return untrustedChain;
            };
        } catch (e) {
            console.log("[-] Conscrypt APEX Bypass failed: " + e);
        }
    });
}
