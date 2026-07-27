/* 
   Core Survival System (V3 Refactored)
   - Goal: Prevent App Crash & Skip Agreement Screen rendering bug.
   - Executed: ALWAYS (Even in --no-filter mode)
*/

console.log("[*] Core Survival System Loaded");

// 1. Android 14/15 MTE (Heap Tagging) Crash Prevention
function patch_heap_tagging() {
    try {
        var libc = Process.getModuleByName("libc.so");
        var mallopt = null;
        var prctl = null;
        
        libc.enumerateExports().forEach(function(exp) {
            if (exp.name === "mallopt") mallopt = exp.address;
            else if (exp.name === "prctl") prctl = exp.address;
        });

        if (mallopt) {
            try {
                var mallopt_func = new NativeFunction(mallopt, 'int', ['int', 'int']);
                mallopt_func(-9, 0); // M_BIONIC_DISABLE_MEMORY_MITIGATIONS
                console.log("[✓] Direct MTE Disable via mallopt(-9) success");
            } catch(e) {}
        }

        if (prctl) {
            try {
                var prctl_func = new NativeFunction(prctl, 'int', ['int', 'uint64', 'uint64', 'uint64', 'uint64']);
                prctl_func(53, 0, 0, 0, 0); // PR_SET_TAGGED_ADDR_CTRL -> 0
                console.log("[✓] Direct MTE Disable via prctl(53) success. (No Interceptor attached to avoid WebView Trap)");
            } catch(e) {}
        }
    } catch(e) {
        console.log("[-] MTE Patch Error: " + e.stack);
    }
}

// 2. FDS Stealth (Hide Root, Magisk, Developer Options)
function hook_stealth() {
    if (!Java.available) return;
    Java.perform(function() {
        try {
            var File = Java.use("java.io.File");
            File.exists.implementation = function() {
                var name = this.getName();
                if (name === "su" || name === "magisk" || name === "frida-server" || name === "busybox") return false;
                return this.exists.call(this);
            };

            var SettingsGlobal = Java.use("android.provider.Settings$Global");
            SettingsGlobal.getInt.overload('android.content.ContentResolver', 'java.lang.String', 'int').implementation = function(cr, name, def) {
                if (name === "development_settings_enabled" || name === "adb_enabled") return 0;
                return this.getInt(cr, name, def);
            };

            // [🛡️ Mock Location Detection Bypass]
            try {
                var Location = Java.use("android.location.Location");
                Location.isFromMockProvider.implementation = function() {
                    return false;
                };
                console.log("[✓] Location.isFromMockProvider bypass applied successfully");
            } catch (err) {
                console.log("[-] Location.isFromMockProvider Hook Error: " + err);
            }

            // MediaCodec SIGBUS Seccomp Bypass
            try {
                var MediaCodec = Java.use("android.media.MediaCodec");
                var IOException = Java.use("java.io.IOException");
                
                MediaCodec.createByCodecName.implementation = function(name) {
                    console.log("[🛡️] Blocked MediaCodec Initialization (createByCodecName): " + name);
                    throw IOException.$new("MediaCodec disabled to prevent Seccomp-BPF SIGBUS");
                };
                MediaCodec.createDecoderByType.implementation = function(type) {
                    console.log("[🛡️] Blocked MediaCodec Initialization (createDecoderByType): " + type);
                    throw IOException.$new("MediaCodec disabled to prevent Seccomp-BPF SIGBUS");
                };
                MediaCodec.createEncoderByType.implementation = function(type) {
                    console.log("[🛡️] Blocked MediaCodec Initialization (createEncoderByType): " + type);
                    throw IOException.$new("MediaCodec disabled to prevent Seccomp-BPF SIGBUS");
                };
            } catch (err) {
                console.log("[-] MediaCodec Hook Error: " + err);
            }

            var SettingsSecure = Java.use("android.provider.Settings$Secure");
            SettingsSecure.getInt.overload('android.content.ContentResolver', 'java.lang.String', 'int').implementation = function(cr, name, def) {
                if (name === "development_settings_enabled" || name === "adb_enabled") return 0;
                return this.getInt(cr, name, def);
            };
        } catch (e) {
            console.log("[-] Stealth Hooks Error: " + e.stack);
        }
    });
}

patch_heap_tagging();
hook_stealth();
