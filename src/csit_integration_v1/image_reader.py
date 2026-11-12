"""Image analysis for the v2 route: real OCR first (Tesseract), a vision model only for images OCR cannot read.

Nothing here executes content from the image or the file. The image is decoded by Pillow with a pixel limit, re-encoded to a plain
PNG in the job directory, and handed to Tesseract as an argument list (no shell). A vision model sees the image only when OCR found
too little text, and what it returns is stored as a description, never as a verbatim transcription (method "Visual" or "Mixed").

A reading with no text at all is not a reading: the caller ends the job Failed EMPTY_EXTRACTION, it is never Completed with nothing.
"""
import io,os,re,shutil,subprocess
from dataclasses import dataclass,field
from pathlib import Path
from .errors import IntegrationError

IMAGE_FORMATS={".png":{"PNG"},".jpg":{"JPEG"},".jpeg":{"JPEG"},".gif":{"GIF"},".bmp":{"BMP"},".tif":{"TIFF"},".tiff":{"TIFF"},".webp":{"WEBP"}}
MAX_PIXELS=int(os.getenv("KM_CSIT_IMAGE_MAX_PIXELS","80000000"))
VISION_MAX_SIDE=2048
VISION_MAX_TEXT=6000
SIGNIFICANT=re.compile(r"[0-9A-Za-zÀ-ɏ぀-ヿ㐀-鿿가-힯]")

@dataclass
class Reading:
    text:str
    method:str                      # "OCR" | "Visual" | "Mixed"  (v2 extraction.method)
    ocr_used:bool
    warnings:list=field(default_factory=list)

def significant(text):
    return len(SIGNIFICANT.findall(text))

def _open(path):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS=MAX_PIXELS
    return Image.open(path)

def inspect(path,suffix):
    """Signature, container and size gate. The extension must match what is inside; nothing is trusted from the file name or declared MIME."""
    from PIL import Image
    try:
        with _open(path) as im:
            fmt=im.format
            w,h=im.size
            if fmt not in IMAGE_FORMATS.get(suffix,set()):
                raise IntegrationError("INVALID_FILE_SIGNATURE","File content is not the image type its extension claims")
            if w*h>MAX_PIXELS:raise IntegrationError("PARSER_LIMIT_EXCEEDED","Image dimensions exceed the limit")
            im.verify()
    except IntegrationError:raise
    except Image.DecompressionBombError:raise IntegrationError("PARSER_LIMIT_EXCEEDED","Image dimensions exceed the limit") from None
    except Exception:raise IntegrationError("CORRUPT_FILE","Image cannot be decoded") from None

def _normalized_png(path,out,max_side=None):
    """First frame, flattened onto white, as a plain RGB PNG (transparency and animation do not reach the OCR or the vision model)."""
    from PIL import Image
    with _open(path) as im:
        im.seek(0)
        im=im.convert("RGBA")
        bg=Image.new("RGB",im.size,"white")
        bg.paste(im,mask=im.getchannel("A"))
    if max_side and max(bg.size)>max_side:
        scale=max_side/max(bg.size)
        bg=bg.resize((max(1,int(bg.width*scale)),max(1,int(bg.height*scale))),Image.LANCZOS)
    bg.save(out,"PNG")
    return out

class ImageReader:
    """vision: bytes(PNG)->str, or None when no vision model is configured."""
    def __init__(self,vision=None,langs=None,min_chars=None,timeout=None,tesseract=None):
        self.vision=vision
        self.langs=langs or os.getenv("KM_CSIT_OCR_LANGS","chi_tra+eng")
        self.min_chars=int(min_chars if min_chars is not None else os.getenv("KM_CSIT_OCR_MIN_CHARS","20"))
        self.timeout=float(timeout if timeout is not None else os.getenv("KM_CSIT_OCR_TIMEOUT","90"))
        self.tesseract=(tesseract or None) if tesseract is not None else shutil.which("tesseract")   # tesseract="" switches OCR off

    @property
    def available(self):
        return bool(self.tesseract) or self.vision is not None

    def _ocr(self,png):
        if not self.tesseract:return None,"OCR engine is not installed in this KM"
        env={"PATH":os.environ.get("PATH",""),"OMP_THREAD_LIMIT":"2","LC_ALL":"C"}
        if os.environ.get("TESSDATA_PREFIX"):env["TESSDATA_PREFIX"]=os.environ["TESSDATA_PREFIX"]
        try:
            r=subprocess.run([self.tesseract,str(png),"stdout","-l",self.langs,"--psm","3"],capture_output=True,timeout=self.timeout,env=env,cwd=str(Path(png).parent),shell=False)
        except subprocess.TimeoutExpired:return None,"OCR timed out"
        except OSError:return None,"OCR engine could not start"
        if r.returncode!=0:return None,"OCR engine failed ("+(r.stderr.decode("utf-8","replace").strip().splitlines() or ["no message"])[-1][:120]+")"
        text="\n".join(line.rstrip() for line in r.stdout.decode("utf-8","replace").replace("\r\n","\n").split("\n"))
        return re.sub(r"\n{3,}","\n\n",text).strip(),None

    def read(self,path,workdir):
        workdir=Path(workdir);workdir.mkdir(parents=True,exist_ok=True)
        warnings=[]
        ocr_png=workdir/"ocr-input.png"
        try:
            _normalized_png(path,ocr_png)
            ocr_text,ocr_problem=self._ocr(ocr_png)
            if ocr_problem:warnings.append(ocr_problem)
            ocr_text=ocr_text or ""
            if significant(ocr_text)>=self.min_chars:
                return Reading(ocr_text,"OCR",True,warnings)
            # Too little text for OCR to be the answer: the image is a photo, a diagram or a chart. Ask the vision model, and say so.
            description=""
            if self.vision is not None:
                vis_png=workdir/"vision-input.png"
                _normalized_png(path,vis_png,VISION_MAX_SIDE)
                try:description=(self.vision(vis_png.read_bytes()) or "").strip()[:VISION_MAX_TEXT]
                except IntegrationError:raise
                except Exception:raise IntegrationError("VISION_UNAVAILABLE","Vision model unavailable",True) from None
            elif not self.tesseract:
                raise IntegrationError("UNSUPPORTED_FORMAT","Image content cannot be analysed: OCR and vision are not enabled in this KM")
            if description:
                warnings.append("image content was described by a vision model; the text is a description, not a verbatim transcription")
                if ocr_text.strip():
                    return Reading(ocr_text.strip()+"\n\n[Visual description]\n"+description,"Mixed",True,warnings)
                return Reading("[Visual description]\n"+description,"Visual",False,warnings)
            if ocr_text.strip():
                warnings.append("only a little text could be read from the image")
                return Reading(ocr_text,"OCR",True,warnings)
            return Reading("","OCR",False,warnings)   # the caller turns an empty reading into Failed EMPTY_EXTRACTION
        finally:
            for name in ("ocr-input.png","vision-input.png"):
                try:(workdir/name).unlink()
                except OSError:pass
