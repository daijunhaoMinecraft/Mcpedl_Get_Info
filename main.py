from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from curl_cffi import requests
import json
import bs4
from bs4 import BeautifulSoup
from urllib.parse import unquote
from typing import Dict, Any, List
import os
import subprocess

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
    """
    获取页面数据，并使用 Node.js 子进程执行 __NUXT__ 脚本。
    """
    try:
        r = requests.get(
            url,
            impersonate="chrome120",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            timeout=20
        )
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"请求目标 URL 失败: {e}")

    soup = BeautifulSoup(r.text, 'lxml')
    nuxt_script_tag = soup.find('script', string=lambda text: text and 'window.__NUXT__' in text)

    if not nuxt_script_tag:
        raise HTTPException(status_code=404, detail="错误: 未能在页面中找到包含'__NUXT__'数据的 script 标签。")

    script_content = nuxt_script_tag.string

    iife_start_index = script_content.find('(function')
    if iife_start_index == -1:
        raise HTTPException(status_code=400, detail="错误: 未能找到 IIFE 函数的起始位置。")

    iife_code = script_content[iife_start_index:]

    # --- 【核心修复】 ---
    # 构造要通过 stdin 传递给 Node.js 的完整脚本
    # 去除 iife_code 最后一个字符，然后反转
    node_script_for_stdin = f"console.log(JSON.stringify({iife_code[:-1]}))"

    try:
        # 运行 Node.js 进程，并通过 stdin 管道传入我们的脚本
        # 这可以完美避免所有命令行特殊字符的转义问题
        result = subprocess.run(
            ['node'],                       # 只启动 node 进程
            input=node_script_for_stdin,    # 将脚本作为标准输入传递
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
        
        nuxt_data = json.loads(result.stdout)

    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="错误: 'node' 命令未找到。请确保你已经在服务器上正确安装了 Node.js 并且其路径已添加到系统 PATH 环境变量中。")
    except subprocess.CalledProcessError as e:
        # e.stderr 会包含 Node.js 报出的真实错误，这对于调试非常有用
        raise HTTPException(status_code=500, detail=f"Node.js 脚本执行失败: {e.stderr}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="错误: 无法解析来自 Node.js 的输出为 JSON。")
    # --- 【修复结束】 ---

    model_data = nuxt_data.get("state", {}).get("slug", {}).get("model", {})
    if not model_data:
        raise HTTPException(status_code=404, detail="错误: 在 __NUXT__ 数据中未能找到预期的 'model' 结构。")
    if "downloads" in model_data:
        for item in model_data["downloads"]:
            if item.get("file") and str(item["file"]).startswith("/leaving"):
                decoded_url = unquote(item["file"].split("url=")[1])
                item["file"] = decoded_url
        
        model_data["downloads"] = remove_duplicates(model_data["downloads"])
        
    if "downloads_vip" in model_data:
        model_data["downloads_vip"] = remove_duplicates(model_data["downloads_vip"])
        
    nuxt_data = clean_dict(nuxt_data)

    return nuxt_data


@app.post("/mcpedl/info")
async def get_download_info(request: URLRequest):
    try:
        if request.url.startswith("https://mcpedl.com"):
            nuxt_data = fetch_nuxt_data(request.url)
            return nuxt_data
        else:
            raise HTTPException(status_code=400, detail=f"错误的Url链接")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"发生未知服务器错误: {str(e)}")


if os.path.exists("index.html"):
    app.mount("/", StaticFiles(directory=".", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
