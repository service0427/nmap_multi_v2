/* 
   Network Hook (V3 Refactored)
   - Exclusively handles Certificate Pinning & SSL Bypass.
   - Bypasses SSL Pinning (Native + OkHttp3 + TrustManager + SSLContext + Chromium).
*/

console.log("[*] Network Hook Script Loaded (Pure SSL Bypass)");

function hook_native_ssl() {
    var modules = Process.enumerateModules();
    modules.forEach(function (m) {
        var name = m.name.toLowerCase();
        if (name === "libssl.so" || name === "libboringssl.so") {
            try {
                var exports = m.enumerateExports();
                exports.forEach(function (exp) {
                    var n = exp.name;
                    if (n.indexOf("SSL_CTX_set_custom_verify") !== -1 || n.indexOf("SSL_set_custom_verify") !== -1 || n.indexOf("SSL_set_verify") !== -1) {
                        try {
                            Interceptor.attach(exp.address, { onEnter: function (args) { args[1] = ptr(0); } });
                        } catch (e) { }
                    }
                    if (n === "SSL_get_verify_result") {
                        try {
                            Interceptor.replace(exp.address, new NativeCallback(function (ssl) { return 0; }, 'long', ['pointer']));
                        } catch (e) { }
                    }
                });
            } catch (e) { }
        }
    });
}

function hook_java_all() {
    if (!Java.available) return;

    Java.perform(function () {
        // --- 1. TrustManager Implementation (The Core Bypass) ---
        var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        var SSLContext = Java.use('javax.net.ssl.SSLContext');

        var TrustManager = null;
        try {
            TrustManager = Java.registerClass({
                name: 'com.example.TrustManager',
                implements: [X509TrustManager],
                methods: {
                    checkClientTrusted: function (chain, authType) { },
                    checkServerTrusted: function (chain, authType) { },
                    getAcceptedIssuers: function () { return []; }
                }
            });
        } catch (e) {
            console.log("[-] Java.registerClass failed (Cache dir not ready). Proceeding without custom TrustManager array.");
        }

        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                return untrustedChain;
            };
        } catch (e) { }

        // --- 2. SSLContext Hook ---
        try {
            if (TrustManager) {
                var TrustManagers = [TrustManager.$new()];
                var SSLContext_init = SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom');
                SSLContext_init.implementation = function (keyManager, trustManager, secureRandom) {
                    SSLContext_init.call(this, keyManager, TrustManagers, secureRandom);
                };
            }
        } catch (e) { }

        // --- 3. OkHttp3 CertificatePinner Bypass ---
        try {
            var CertificatePinner = Java.use("okhttp3.CertificatePinner");
            CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function (hostname, certs) {
                return;
            };
        } catch (e) { }

        // --- 4. Android WebView (Chromium) SSL Bypass ---
        try {
            var X509Util = Java.use("org.chromium.net.X509Util");
            X509Util.verifyServerCertificates.overload('[[B', 'java.lang.String', 'java.lang.String').implementation = function (chain, authType, host) {
                return Java.use("java.util.Collections").emptyList();
            };
        } catch (e) { }

        try {
            var SslErrorHandler = Java.use("android.webkit.SslErrorHandler");
            SslErrorHandler.proceed.implementation = function () {
                this.proceed();
            };
            var WebViewClient = Java.use("android.webkit.WebViewClient");
            WebViewClient.onReceivedSslError.implementation = function (view, handler, error) {
                handler.proceed();
            };
        } catch (e) { }
    });
}

hook_native_ssl();
hook_java_all();
