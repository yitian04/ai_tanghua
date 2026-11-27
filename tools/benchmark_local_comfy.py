"""Generate and record a serial comparison using the six shop catalog styles."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from src.pipeline.image_generation.local_comfy import LocalImageProvider, LocalSettings
from src.pipeline.image_generation.providers import ImageProviderError, ImageRequestOptions
from src.pipeline.image_generation.quality import evaluate_traceable_line_image
from src.pipeline.shop_creation import SDXL_LINE_NEGATIVE, catalog, image_prompt, sdxl_line_prompt
from src.pipeline.shop_window import build_example

THEMES = [
    "A cup of hot coffee and a croissant, with two long curves of steam",
    "A round sun, triangular mountain peaks, and a gently curving river",
    "A long sweeping ocean wave carrying a small sailboat",
    "Two large mirrored leafy branches surrounding a flower",
    "A large umbrella beside two round-toed rain boots",
    "A gentle hill, a large cloud and a half-visible sun",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["installed", "klein"], default="installed")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--concise-direct", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    name = "comparison" if args.profile == "installed" else "klein"
    output = root / "outputs" / "local_comfy" / ("concise-direct" if args.concise_direct else name)
    if (output / "results.jsonl").exists():
        output = output.with_name(f"{output.name}-{datetime.now():%Y%m%d-%H%M%S}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "results.jsonl"
    settings = LocalSettings.load(root)
    settings.profile = args.profile
    provider = LocalImageProvider(settings)
    options = ImageRequestOptions(size="1536x864", extra_body={"seed": 7343})
    template = (root / "resources" / "shop_whitebox" / "template_curves.json").read_bytes()
    for style, theme in zip(catalog(root)[:args.limit], THEMES):
        prefix = output / style["id"]
        sample = prefix.with_suffix(".sugar.png")
        stages = ("direct",) if args.concise_direct else ("sugar", "edit", "direct")
        for stage in stages:
            destination = prefix.with_suffix(f".{stage}.png")
            prompt = image_prompt(style, theme)
            if args.concise_direct:
                prompt = sdxl_line_prompt(style, theme)
                options.extra_body["negative_prompt"] = SDXL_LINE_NEGATIVE
            record = {"style": style["id"], "theme": theme, "stage": stage}
            try:
                if stage == "sugar":
                    prompt = ("Overhead view of traditional Chinese sugar painting. Thin amber caramel strands "
                              "draw simple smooth single strokes on plain white parchment. No shading, text, or stick. "
                              f"Landscape composition: {theme}.")
                elif stage == "edit":
                    prompt = ("Convert the input caramel strands into uniform black centerline strokes on white. "
                              "Keep all main objects and their positions. Replace each caramel strand with exactly "
                              "one stroke. Remove colors, texture, shadows and doubled edges.")
                if stage == "edit":
                    result = provider.edit(prompt, sample, destination, options)
                else:
                    result = provider.generate(prompt, destination, options)
                record.update(path=str(result.output_path), usage=result.usage)
                if stage != "sugar":
                    quality = evaluate_traceable_line_image(result.output_path)
                    record.update(score=quality.score, accepted=quality.accepted)
                    if quality.accepted:
                        content, merged, stats = build_example(template, result.output_path.read_bytes())
                        record["curve_count"] = len(content.curves)
                        record["window_stats"] = stats
                        destination.with_suffix(".curves.json").write_text(
                            json.dumps(merged.to_dict(), ensure_ascii=False), encoding="utf-8",
                        )
            except (OSError, ValueError, ImageProviderError) as exc:
                record["error"] = str(exc)
            record["prompt"] = prompt
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(record["style"], stage, record.get("error", record.get("accepted", "generated")), flush=True)


if __name__ == "__main__":
    main()
