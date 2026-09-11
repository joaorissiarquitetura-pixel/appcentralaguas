from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "app" / "static" / "icons"
ANDROID_RES = ROOT / "android" / "app" / "src" / "main" / "res"
SOURCE_CANDIDATES = (
    OUTPUT / "central_aguas_icon_source.png",
    ROOT / "app" / "static" / "assets" / "gotinha" / "emotions" / "alegria.webp",
)
RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS
WHITE = (255, 255, 255, 255)
ANDROID_DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def find_source() -> Path:
    for candidate in SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Nenhuma imagem fonte de icone foi encontrada.")


def build_square(source: Image.Image, size: int, inset_ratio: float = 0) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), WHITE)
    inset = int(size * inset_ratio)
    art = ImageOps.fit(
        source,
        (size - inset * 2, size - inset * 2),
        method=RESAMPLE,
        centering=(0.5, 0.5),
    )
    canvas.alpha_composite(art, (inset, inset))
    return canvas.convert("RGB")


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def build_pwa_icons(source: Image.Image) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        save_png(build_square(source, size), OUTPUT / f"icon-{size}.png")
        save_png(build_square(source, size, inset_ratio=0.04), OUTPUT / f"icon-maskable-{size}.png")


def build_android_icons(source: Image.Image) -> None:
    for density, size in ANDROID_DENSITIES.items():
        directory = ANDROID_RES / density
        icon = build_square(source, size)
        save_png(icon, directory / "ic_launcher.png")
        save_png(icon, directory / "ic_launcher_round.png")
        save_png(icon, directory / "ic_launcher_foreground.png")


def main() -> None:
    source = Image.open(find_source()).convert("RGBA")
    build_pwa_icons(source)
    build_android_icons(source)


if __name__ == "__main__":
    main()
