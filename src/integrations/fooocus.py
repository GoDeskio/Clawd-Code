"""Jonathan-native local diffusion image engine (legacy Fooocus API surface)."""
from __future__ import annotations
import importlib.util
import os,subprocess,sys,uuid
from datetime import datetime
from pathlib import Path
from typing import Any,Callable
FOOOCUS_REPOSITORY="https://github.com/lllyasviel/Fooocus.git"; DEFAULT_PORT=7865

def install_python_310(*_args:Any,**_kwargs:Any)->Path|None: return None

class FooocusManager:
    """Preserves callers while using Jonathan's own Diffusers implementation."""
    def __init__(self,source_dir:str|Path)->None:
        self.source_dir=Path(source_dir).expanduser().resolve(); self.checkout=self.source_dir/"src"/"integrations"; self.venv=self.source_dir/".venv"; self.outputs=self.source_dir/"integrations"/"Fooocus-outputs"; self.cache=self.source_dir/"integrations"/".image-models"; self.port=0
    @staticmethod
    def _deps()->tuple[bool,list[str]]:
        missing=[module for module in ("torch","diffusers","transformers","safetensors","PIL") if importlib.util.find_spec(module) is None]
        return not missing,missing
    def status(self)->dict[str,Any]:
        ready,missing=self._deps(); model=os.environ.get("JONATHAN_IMAGE_MODEL","stabilityai/sdxl-turbo")
        return {"cloned":False,"source_ready":True,"dependencies_ready":ready,"runtime_ready":ready,"running":ready,"reachable":ready,"url":"","port":0,"path":str(self.checkout),"venv":str(self.venv),"outputs":str(self.outputs),"repository":"internal://jonathan/local-diffusion","reference_repository":FOOOCUS_REPOSITORY,"revision":"jonathan-native-1","backend":"diffusers","model":model,"missing":missing,"payments_required":False}
    def install(self,progress:Callable[[str],None]|None=None)->dict[str,Any]:
        ready,missing=self._deps()
        if not ready:
            if progress: progress(f"Installing Jonathan local diffusion packages: {', '.join(missing)}")
            result=subprocess.run([sys.executable,"-m","pip","install","torch>=2.4","diffusers>=0.35","accelerate>=1.0","transformers>=4.48","safetensors>=0.5"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=1800,check=False)
            if result.returncode!=0: raise RuntimeError(result.stderr[-4000:] or "Local diffusion dependency install failed")
        self.outputs.mkdir(parents=True,exist_ok=True); self.cache.mkdir(parents=True,exist_ok=True)
        status=self.status()
        if not status["dependencies_ready"]: raise RuntimeError(f"Missing local diffusion dependencies: {status['missing']}")
        return status
    def start(self,*,install:bool=True,progress:Callable[[str],None]|None=None)->dict[str,Any]: return self.install(progress) if install else self.status()
    def stop(self)->dict[str,Any]: return {**self.status(),"running":False,"message":"No background image service is used; model memory is released after each generation."}
    def latest_outputs(self,limit:int=20)->list[dict[str,Any]]:
        if not self.outputs.is_dir(): return []
        rows=[]
        for path in sorted((p for p in self.outputs.rglob("*") if p.is_file() and p.suffix.lower() in {".png",".jpg",".jpeg",".webp"}),key=lambda p:p.stat().st_mtime,reverse=True)[:max(1,limit)]: rows.append({"path":str(path.resolve()),"name":path.name,"size":path.stat().st_size,"modified":path.stat().st_mtime})
        return rows
    def generate(self,prompt:str,*,negative_prompt:str="",width:int=1024,height:int=1024,performance:str="Speed",steps:int|None=None,seed:int|None=None,source_image:str|Path|None=None,strength:float=.65,timeout:int=1800,progress:Callable[[str],None]|None=None)->dict[str,Any]:
        if not prompt.strip(): raise ValueError("Image prompt is required")
        self.install(progress); import torch
        from PIL import Image
        from diffusers import AutoPipelineForImage2Image,AutoPipelineForText2Image
        model=os.environ.get("JONATHAN_IMAGE_MODEL","stabilityai/sdxl-turbo"); use_cuda=torch.cuda.is_available(); dtype=torch.float16 if use_cuda else torch.float32
        cls=AutoPipelineForImage2Image if source_image else AutoPipelineForText2Image
        if progress: progress(f"Loading Jonathan local image model {model}")
        pipe=cls.from_pretrained(model,torch_dtype=dtype,cache_dir=str(self.cache),use_safetensors=True)
        if use_cuda: pipe=pipe.to("cuda")
        else:
            pipe=pipe.to("cpu")
            if hasattr(pipe,"enable_attention_slicing"): pipe.enable_attention_slicing()
        generator=torch.Generator(device="cuda" if use_cuda else "cpu").manual_seed(int(seed if seed is not None else uuid.uuid4().int%(2**31)))
        count=int(steps or (2 if str(performance).lower() in {"speed","extreme speed","lightning","hyper-sd"} else 4)); kwargs={"prompt":prompt,"negative_prompt":negative_prompt or None,"num_inference_steps":max(1,min(count,30)),"guidance_scale":0.0,"generator":generator}
        if source_image:
            source=Path(source_image).expanduser().resolve()
            if not source.is_file(): raise ValueError(f"Source image does not exist: {source}")
            with Image.open(source) as opened: kwargs["image"]=opened.convert("RGB").resize((width,height))
            kwargs["strength"]=max(.05,min(float(strength),.95))
        else: kwargs.update(width=max(256,min(width,2048)),height=max(256,min(height,2048)))
        try: image=pipe(**kwargs).images[0]
        finally:
            del pipe
            if use_cuda: torch.cuda.empty_cache()
        folder=self.outputs/datetime.now().strftime("%Y-%m-%d"); folder.mkdir(parents=True,exist_ok=True); target=folder/f"jonathan-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:8]}.png"; image.save(target)
        item={"path":str(target.resolve()),"name":target.name,"size":target.stat().st_size}
        return {**self.status(),"ok":True,"outputs":[item],"engine":"jonathan-local-diffusion","model":model,"device":"cuda" if use_cuda else "cpu"}
