from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from curl_cffi import requests
import json
import bs4
from bs4 import BeautifulSoup
import js2py
from urllib.parse import unquote
from typing import Dict, Any, List
import os


app = FastAPI()

class URLRequest(BaseModel):
    url: str


def remove_duplicates(items: List[Dict]) -> List[Dict]:
    """
    根据file字段去除重复项
    """
    seen_files = set()
    unique_items = []
    for item in items:
        file_url = item.get("file")
        if file_url not in seen_files:
            seen_files.add(file_url)
            unique_items.append(item)
    return unique_items


def clean_text(text):
    """
    清理文本中的特殊字符
    """
    if isinstance(text, str):
        # 移除可能导致编码问题的字符
        return text.encode('utf-8', errors='ignore').decode('utf-8')
    return text


def clean_dict(obj):
    """
    递归清理字典中的特殊字符
    """
    if isinstance(obj, dict):
        return {key: clean_dict(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_dict(item) for item in obj]
    else:
        return clean_text(obj)


def fetch_nuxt_data(url: str) -> Dict[Any, Any]:
    # 模拟 Chrome 120 的指纹（包括 TLS、HTTP2、ALPN、Header 顺序等）
    r = requests.get(
        url,
        impersonate="chrome120",  # 关键！模拟真实浏览器指纹
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

    soup = BeautifulSoup(r.text, 'lxml')
    nuxt_script_tag = soup.find('script', string=lambda text: text and 'window.__NUXT__' in text)

    if not nuxt_script_tag:
        raise HTTPException(status_code=400, detail="错误: 未能在文件中找到包含'__NUXT__'数据的 script 标签。")

    script_content = nuxt_script_tag.string

    iife_start_index = script_content.find('(function')
    if iife_start_index == -1:
        raise HTTPException(status_code=400, detail="错误: 未能找到 IIFE 函数的起始位置。")

    iife_code = script_content[iife_start_index:]

    # 使用 js2py 执行 JS 代码
    js_result = js2py.eval_js(iife_code)
    # js2py 返回一个特殊对象，我们需要将其转换为 Python 字典
    nuxt_data = js_result.to_dict()

    # 处理下载链接
    for i in nuxt_data["state"]["slug"]["model"]["downloads"]:
        if str(i["file"]).startswith("/"):
            decoded_url = unquote(''.join(i["file"].split("url=")[1::]))
            i["file"] = decoded_url
            
    # 去除 downloads 中的重复项
    if "downloads" in nuxt_data["state"]["slug"]["model"]:
        nuxt_data["state"]["slug"]["model"]["downloads"] = remove_duplicates(
            nuxt_data["state"]["slug"]["model"]["downloads"]
        )
        
    # 去除 downloads_vip 中的重复项
    if "downloads_vip" in nuxt_data["state"]["slug"]["model"]:
        nuxt_data["state"]["slug"]["model"]["downloads_vip"] = remove_duplicates(
            nuxt_data["state"]["slug"]["model"]["downloads_vip"]
        )
        
    # 清理数据中的特殊字符
    nuxt_data = clean_dict(nuxt_data)

    return nuxt_data


@app.post("/mcpedl/info")
async def get_download_info(request: URLRequest):
    try:
        nuxt_data = fetch_nuxt_data(request.url)
        return nuxt_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 挂载静态文件目录，提供HTML页面访问
if os.path.exists("index.html"):
    app.mount("/", StaticFiles(directory=".", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)