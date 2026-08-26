"""Jonathan-native deterministic procedural character and rig generator."""

from __future__ import annotations

import colorsys
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

KINDERGRIMM_REFERENCE = "https://github.com/albertobeiz/kindergrimm"


def _color(h: float, s: float, l: float) -> str:
    r,g,b=colorsys.hls_to_rgb(h%1,l,s); return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def generate_character(output_dir: str|Path, *, seed: str="jonathan", name: str="", species: str="auto", medium: str="ink") -> dict[str,Any]:
    target=Path(output_dir).expanduser().resolve(); target.mkdir(parents=True,exist_ok=True)
    seed=str(seed)
    digest=hashlib.sha256(seed.encode("utf-8")).digest(); rng=random.Random(digest)
    chosen=species if species!="auto" else rng.choice(["human","cat","dog","fox","rabbit","bear"])
    display=name.strip() or rng.choice(["Pip","Moss","Orla","Juniper","Tinker","Ember"])
    base=rng.random(); skin=_color(base,.42,.68); accent=_color(base+.34,.62,.48); dark=_color(base,.35,.18); paper="#f4edda"
    ear={"cat":"polygon","fox":"polygon","rabbit":"long","dog":"flop","bear":"round"}.get(chosen,"round")
    eye_y=142+rng.randint(-5,5); eye_gap=46+rng.randint(-8,8); mouth_y=190+rng.randint(-4,8)
    if ear=="long": ears='<ellipse cx="105" cy="64" rx="22" ry="62"/><ellipse cx="215" cy="64" rx="22" ry="62"/>'
    elif ear=="polygon": ears='<path d="M82 98 L104 26 L138 101 Z"/><path d="M182 101 L216 26 L238 98 Z"/>'
    elif ear=="flop": ears='<path d="M90 86 Q35 78 61 154 Q85 172 111 112Z"/><path d="M230 86 Q285 78 259 154 Q235 172 209 112Z"/>'
    else: ears='<circle cx="92" cy="88" r="38"/><circle cx="228" cy="88" r="38"/>'
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="420" viewBox="0 0 320 420">
<style>.boil{{animation:boil .8s steps(2) infinite;transform-origin:center}}.blink{{animation:blink 4.7s infinite;transform-origin:center}}@keyframes boil{{50%{{transform:rotate(.35deg)}}}}@keyframes blink{{0%,94%,100%{{transform:scaleY(1)}}96%{{transform:scaleY(.08)}}}}</style>
<rect width="320" height="420" rx="24" fill="{paper}"/><g id="rig" class="boil" stroke="{dark}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
<g id="ears" fill="{accent}">{ears}</g><g id="body" fill="{accent}"><path d="M82 393 Q76 270 116 239 Q160 218 204 239 Q244 270 238 393Z"/></g>
<g id="head" fill="{skin}"><path d="M72 145 Q75 72 160 68 Q245 72 248 145 Q250 231 160 251 Q70 231 72 145Z"/></g>
<g id="eyes" class="blink" fill="{dark}" stroke="none"><ellipse cx="{160-eye_gap}" cy="{eye_y}" rx="11" ry="15"/><ellipse cx="{160+eye_gap}" cy="{eye_y}" rx="11" ry="15"/></g>
<g id="nose" fill="{accent}"><path d="M148 167 Q160 158 172 167 L160 179Z"/></g><g id="mouth" fill="none"><path d="M160 179 Q151 {mouth_y} 134 {mouth_y-2} M160 179 Q169 {mouth_y} 186 {mouth_y-2}"/></g>
<g id="arms" fill="none"><path d="M102 282 Q54 310 73 357"/><path d="M218 282 Q266 310 247 357"/></g></g>
<text x="160" y="408" text-anchor="middle" font-family="system-ui,sans-serif" font-size="16" fill="{dark}">{display}</text></svg>'''
    stem=re.sub(r"[^a-z0-9]+","-",display.lower()).strip("-") or "character"
    svg_path=target/f"{stem}.svg"; svg_path.write_text(svg,encoding="utf-8")
    recipe={"name":display,"seed":seed,"species":chosen,"medium":medium,"palette":{"paper":paper,"skin":skin,"accent":accent,"ink":dark},"rig":{"bones":["body","head","ears","eyes","nose","mouth","arms"],"animations":["boil","blink"]},"reference":KINDERGRIMM_REFERENCE}
    json_path=target/f"{stem}.character.json"; json_path.write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"name":display,"seed":seed,"species":chosen,"svg":str(svg_path),"recipe":str(json_path),"artifacts":[str(svg_path),str(json_path)],"repository":"internal://jonathan/character-studio","reference_repository":KINDERGRIMM_REFERENCE}
