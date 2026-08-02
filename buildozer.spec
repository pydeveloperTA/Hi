[app]
title = Travel Assistant
package.name = travelassistant
package.domain = org.travelassistant
version = 1.0
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,db
requirements = python3,kivy==2.3.0,plyer,yt-dlp,android,pyjnius,https://github.com/kivy-garden/mapview/archive/refs/heads/master.zip
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
warn_on_root = 0
