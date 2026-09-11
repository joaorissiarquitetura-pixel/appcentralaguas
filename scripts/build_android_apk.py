import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "app" / "src" / "main"
RES = ANDROID / "res"
BUILD = ROOT / "android" / "build"
DIST = ROOT / "android" / "dist"
PACKAGE = "com.centralaguas.app"
SDK = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or r"C:\Users\João Rissi\AppData\Local\Android\Sdk")
BUILD_TOOLS = SDK / "build-tools" / "36.0.0"
PLATFORM = SDK / "platforms" / "android-36" / "android.jar"
KEYSTORE = ROOT / "android" / "central-aguas-debug.keystore"
KEY_ALIAS = "centralaguas"
KEY_PASSWORD = "centralaguas"


def run(args: list[str]) -> None:
    print(" ".join(str(arg) for arg in args))
    subprocess.run(args, check=True)


def tool(name: str) -> str:
    suffix = ".bat" if name in {"d8", "apksigner"} else ".exe"
    return str(BUILD_TOOLS / f"{name}{suffix}")


def generate_mipmap_icons() -> None:
    source = Image.open(ROOT / "app" / "static" / "assets" / "gotinha" / "emotions" / "alegria.webp").convert("RGBA")
    densities = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder, size in densities.items():
        target = RES / folder
        target.mkdir(parents=True, exist_ok=True)
        for name, padding in (("ic_launcher.png", 0.10), ("ic_launcher_round.png", 0.10), ("ic_launcher_foreground.png", 0.16)):
            canvas = Image.new("RGBA", (size, size), (11, 76, 203, 255))
            mascot = ImageOps.contain(source, (int(size * (1 - padding * 2)), int(size * (1 - padding * 2))))
            canvas.alpha_composite(mascot, ((size - mascot.width) // 2, (size - mascot.height) // 2))
            canvas.convert("RGB").save(target / name, optimize=True)


def ensure_debug_keystore() -> None:
    if KEYSTORE.exists():
        return
    run([
        "keytool",
        "-genkeypair",
        "-v",
        "-keystore",
        str(KEYSTORE),
        "-storepass",
        KEY_PASSWORD,
        "-keypass",
        KEY_PASSWORD,
        "-alias",
        KEY_ALIAS,
        "-keyalg",
        "RSA",
        "-keysize",
        "2048",
        "-validity",
        "10000",
        "-dname",
        "CN=Central Aguas, OU=App, O=Central Aguas, L=Votuporanga, S=SP, C=BR",
    ])


def main() -> None:
    generate_mipmap_icons()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    DIST.mkdir(parents=True, exist_ok=True)
    (BUILD / "compiled").mkdir(parents=True)
    (BUILD / "gen").mkdir(parents=True)
    (BUILD / "classes").mkdir(parents=True)
    (BUILD / "dex").mkdir(parents=True)

    compiled = BUILD / "compiled" / "resources.zip"
    unsigned = BUILD / "central-aguas-unsigned.apk"
    dex_apk = BUILD / "central-aguas-dex.apk"
    aligned = BUILD / "central-aguas-aligned.apk"
    signed = DIST / "central-aguas-debug.apk"

    run([tool("aapt2"), "compile", "--dir", str(RES), "-o", str(compiled)])
    run([
        tool("aapt2"),
        "link",
        "-I",
        str(PLATFORM),
        "--manifest",
        str(ANDROID / "AndroidManifest.xml"),
        "--java",
        str(BUILD / "gen"),
        "--auto-add-overlay",
        "-o",
        str(unsigned),
        str(compiled),
    ])

    java_files = [str(path) for path in (ANDROID / "java").rglob("*.java")]
    java_files += [str(path) for path in (BUILD / "gen").rglob("*.java")]
    run(["javac", "-encoding", "UTF-8", "-classpath", str(PLATFORM), "-d", str(BUILD / "classes"), *java_files])
    class_files = [str(path) for path in (BUILD / "classes").rglob("*.class")]
    run([tool("d8"), "--lib", str(PLATFORM), "--output", str(BUILD / "dex"), *class_files])

    shutil.copyfile(unsigned, dex_apk)
    run(["jar", "uf", str(dex_apk), "-C", str(BUILD / "dex"), "classes.dex"])
    run([tool("zipalign"), "-f", "-p", "4", str(dex_apk), str(aligned)])
    ensure_debug_keystore()
    run([
        tool("apksigner"),
        "sign",
        "--ks",
        str(KEYSTORE),
        "--ks-key-alias",
        KEY_ALIAS,
        "--ks-pass",
        f"pass:{KEY_PASSWORD}",
        "--key-pass",
        f"pass:{KEY_PASSWORD}",
        "--out",
        str(signed),
        str(aligned),
    ])
    run([tool("apksigner"), "verify", "--verbose", str(signed)])
    print(f"APK generated at {signed}")


if __name__ == "__main__":
    main()
