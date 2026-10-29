#!/usr/bin/env bash
set -euo pipefail

# Direct image-selector canary, not an automatic-importer mapping test.
echo 'LAB_SELECTOR=macos.version=15.x,macos.purpose=githubrunner,image.with=xcode-26'
test "$(uname -s)" = Darwin
test "$(uname -m)" = arm64
test "$(sw_vers -productVersion | cut -d. -f1)" = 15
sw_vers
uname -m
echo LAB_IMAGE_DEFAULT
xcode-select -p
xcodebuild -version
for app in /Applications/Xcode*.app; do
  printf 'LAB_INSTALLED_XCODE %s ' "$app"
  /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/version.plist"
  /usr/libexec/PlistBuddy -c 'Print :ProductBuildVersion' "$app/Contents/version.plist"
done

root=$(mktemp -d "$HOME/gha-xcode26-canary-XXXXXXXX")
git -C "$root" init
git -C "$root" fetch --no-tags --depth=1 https://github.com/nicklockwood/SwiftFormat.git 468a7d32dedc8d352c191594b3b45d9fd8ba291b
git -C "$root" checkout --detach FETCH_HEAD
cd "$root"
test "$(git rev-parse HEAD)" = 468a7d32dedc8d352c191594b3b45d9fd8ba291b

# Prefer the image default if it is Xcode26; otherwise explicitly choose installed26.
if ! xcodebuild -version | head -1 | grep -q '^Xcode 26'; then
  selected=''
  for app in /Applications/Xcode*.app; do
    version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/version.plist")
    case "$version" in 26*) selected="$app" ;; esac
  done
  test -n "$selected"
  sudo xcode-select -s "$selected/Contents/Developer"
fi
echo LAB_TEST_TOOLCHAIN
xcode-select -p
xcodebuild -version
xcodebuild -version | head -1 | grep '^Xcode 26'
swift --version
git config user.name 'test user'
git config user.email test.user@noreply.com
xcodebuild -project SwiftFormat.xcodeproj -scheme 'SwiftFormat (Framework)' -sdk macosx clean build test -enableCodeCoverage YES -derivedDataPath Build/
cd Build/Build/ProfileData
cd $(ls -d */ | head -n 1)
directory=${PWD##*/}
pathCoverage=Build/Build/ProfileData/${directory}/Coverage.profdata
cd ../../../../
xcrun llvm-cov export -format=lcov -instr-profile "$pathCoverage" Build/Build/Products/Debug/SwiftFormat.framework/SwiftFormat > info.lcov
test -s info.lcov
echo LAB_FRAMEWORK_PASS

# Direct action smoke test, not the compatibility runtime's mise/cache bootstrap.
git init action
git -C action fetch --no-tags --depth=1 https://github.com/maxim-lobanov/setup-xcode.git ed7a3b1fda3918c0306d1b724322adc0b8cc0a90
git -C action checkout --detach FETCH_HEAD
start=$(date +%s)
url=https://nodejs.org/dist/v24.18.0/node-v24.18.0-darwin-arm64.tar.gz
echo "LAB_NODE_DOWNLOAD=$url"
curl --fail --location --max-time 180 "$url" -o node.tar.gz
curl --fail --location --max-time 30 https://nodejs.org/dist/v24.18.0/SHASUMS256.txt -o SHASUMS256.txt
mv node.tar.gz node-v24.18.0-darwin-arm64.tar.gz
grep ' node-v24.18.0-darwin-arm64.tar.gz$' SHASUMS256.txt | shasum -a 256 -c -
tar -xzf node-v24.18.0-darwin-arm64.tar.gz
touch action-env action-output
env 'INPUT_XCODE-VERSION=26' GITHUB_ENV="$root/action-env" GITHUB_OUTPUT="$root/action-output" ./node-v24.18.0-darwin-arm64/bin/node action/dist/index.js
echo "LAB_DIRECT_JS_SECONDS=$(( $(date +%s) - start ))"
xcodebuild -version
echo LAB_DIRECT_JS_PASS
