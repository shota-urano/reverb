# Reverb ビルド/テスト（macOS / Apple Silicon）
#
# full Xcode 環境では `swift test` がそのまま動く。Command Line Tools のみの環境では
# Swift Testing の framework パスが既定の探索に含まれないため、本 Makefile が自動で付与する。

CLT_FW := /Library/Developer/CommandLineTools/Library/Developer/Frameworks
CLT_LIB := /Library/Developer/CommandLineTools/Library/Developer/usr/lib

# full Xcode（xctest が見つかる）なら追加フラグ不要。なければ Testing の探索パスを足す。
ifeq ($(shell xcrun --find xctest >/dev/null 2>&1 && echo yes),yes)
TEST_FLAGS :=
else
TEST_FLAGS := -Xswiftc -F -Xswiftc $(CLT_FW) \
              -Xlinker -F -Xlinker $(CLT_FW) \
              -Xlinker -rpath -Xlinker $(CLT_FW) \
              -Xlinker -rpath -Xlinker $(CLT_LIB)
endif

.PHONY: build test run clean app

build:
	swift build

test:
	swift test $(TEST_FLAGS)

run:
	swift run Reverb

# 配布可能な自己完結 .app を dist/Reverb.app に生成する（scripts/build_app.sh）。
app:
	./scripts/build_app.sh

clean:
	swift package clean
