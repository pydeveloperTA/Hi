[app]

# Package name (must be valid Java package name)
package.name = travelassistant
package.domain = org.example

# Source files
source.dir = .
source.include_exts = py,png,jpg,kv,atlas

# Python version
requirements = python3,kivy,kivy_garden.mapview,plyer,yt-dlp,android,pyjnius

# Skip the root warning
buildozer.warn_on_root = 0

# Android SDK/NDK (match what's in the container)
android.sdk = 31
android.ndk = 23b
android.api = 31
android.accept_sdk_license = True
buildozer.warn_on_root = 0android.sdk = 31
android.ndk = 23b
android.api = 31
android.accept_sdk_license = True
buildozer.warn_on_root = 0

# API levels
android.api = 31
android.minapi = 21

# Permissions
android.permissions = INTERNET,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_NETWORK_STATE,POST_NOTIFICATIONS

# Gradle dependencies
android.gradle_dependencies = 
