[app]

# (str) Title of your application
title = Travel Assistant

# (str) Package name
package.name = travelassistant

# (str) Package domain (needed for android/ios packaging)
package.domain = org.travelassistant

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,db

# (list) Application requirements
requirements = python3,kivy==2.3.0,kivy_garden.mapview,plyer,yt-dlp,android,pyjnius

# (str) Supported orientations (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (str) Presplash of the application
# presplash.filename = 

# (str) Icon of the application
# icon.filename = 

# (str) The Android arch to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
android.archs = arm64-v8a, armeabi-v7a

# (int) Android API level to use
android.api = 33

# (int) Minimum API required
android.minapi = 21

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

# (list) Java classes to add as activities to the manifest.
# android.add_activities = 

# (str) python-for-android branch to use, defaults to master
p4a.branch = develop

# (str) Bootstrap for Android (sdl2 or webview)
p4a.bootstrap = sdl2

# (list) Gradle dependencies to install
# android.gradle_dependencies = 

# (str) Custom source directory for p4a
# p4a.source_dir = 

# (str) The directory in which python-for-android should look for your own build recipes (if any)
# p4a.local_recipes = 

# (str) Filename to the hook for p4a
# p4a.hook = 

# (str) Bootstrap for iOS
# ios.bootstrap = 

# (str) iOS bundle identifier
# ios.bundle_identifier = org.travelassistant.travelassistant

# (str) iOS app version
# ios.version = 1.0

# (list) iOS frameworks to link against
# ios.frameworks = 

# (list) iOS libraries to link against
# ios.libraries = 

# (str) iOS app category
# ios.category = Navigation

# (str) iOS device family (iphone, ipad or all)
# ios.device_family = iphone

# (bool) Whether to enable automatic signing for iOS
# ios.allow_automatic_signing = True

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 0

# (str) Path to build artifact storage, absolute or relative to spec file
# build_dir = ./.buildozer

# (str) Path to build output (i.e. .apk, .aab) storage
# bin_dir = ./bin

#    -----------------------------------------------------------------------------
#    List as sections
#    You can define all the "list" as [section:key].
#    Each line will be considered as a option to the list.
#    Let's take [app] / source.exclude_patterns.
#    Instead of doing:
#
#[app]
#source.exclude_patterns = license,data/audio/*.wav
#
#    This can be translated into:
#
#[app:source.exclude_patterns]
#license
#data/audio/*.wav
