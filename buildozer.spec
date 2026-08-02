[app]
title = Travel Assistant
package.name = travelassistant
package.domain = org.travelassistant
version = 1.0
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,db
requirements = python3,kivy==2.3.0,kivy_garden.mapview,plyer,yt-dlp,android,pyjnius
orientation = portrait
android.archs = arm64-v8a, armeabi-v7a
android.api = 33
android.minapi = 21
android.sdk = 33
android.ndk = 25c
android.accept_sdk_license = True
android.permissions = INTERNET, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, POST_NOTIFICATIONS, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
p4a.branch = develop
p4a.bootstrap = sdl2
android.use_androidx = True

[buildozer]
log_level = 2
warn_on_root = 0android.minapi = 21

# (int) Android SDK version to use
android.sdk = 33

# (str) Android NDK version to use
android.ndk = 25c

# (bool) Use AndroidX (Android Kivy 2.2.0+)
android.use_androidx = True

# (bool) Automatically accept SDK license agreements
android.accept_sdk_license = True

# (list) Permissions
android.permissions = INTERNET, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, POST_NOTIFICATIONS, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

# (str) python-for-android branch to use, defaults to master
p4a.branch = develop

# (str) Bootstrap for Android (sdl2 or webview)
p4a.bootstrap = sdl2

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 0
