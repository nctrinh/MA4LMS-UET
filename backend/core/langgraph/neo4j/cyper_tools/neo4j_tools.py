import json
import os
import re
import urllib
from pathlib import Path

import requests
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate

from backend.core.config import get_cypher_llm
from backend.core.langgraph.neo4j.cyper_tools.neo4j_utils import Neo4jConnector
from backend.core.prompt.cypher_generator_prompt import cypher_generator_prompt

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# Database Connector


def get_neo4j_connector():
    return Neo4jConnector(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

# Remove the direct initialization


def init_cypher_tools(neo4j_connector, llm_for_cypher):
    # Convert string prompt to PromptTemplate
    prompt_template = PromptTemplate(
        template=cypher_generator_prompt,
        input_variables=["nl_question"]
    )
    # Replace LLMChain with RunnableSequence using pipe operator
    cypher_chain = prompt_template | llm_for_cypher

    def cypher_executor_tool(cypher_query: str) -> str:
        """
        Thực thi Cypher query trên Neo4j và trả về kết quả dạng text
        để agent ReAct có thể đọc như Observation.
        """
        try:
            records = neo4j_connector.run_cypher(cypher_query)
            if not records:
                return "Không tìm thấy kết quả nào từ Neo4j."
            lines = [
                ", ".join(f"{k}: {v}" for k, v in rec.items())
                for rec in records
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Error khi chạy Cypher: {e}"

    def cypher_generator_tool(nl_question: str) -> str:
        """
        Tool để chuyển câu hỏi ngôn ngữ tự nhiên thành câu lệnh Cypher (string).
        Dành cho agent kiểu ReAct nên trả về chuỗi trực tiếp.
        """
        response = cypher_chain.invoke({"nl_question": nl_question})
        cypher_query = response.content.strip().strip('"')
        return cypher_query

    return cypher_executor_tool, cypher_generator_tool


def download_files_for_course(urls_text: str, course_name: str):
    """
    Tool để tải các file trong 1 course từ url có trong knowledge graph neo4j.
    Mỗi folder của mỗi course sẽ có 1 file `urls.json` để lưu các URL đã tải.
    Khi chạy lại, hàm sẽ so sánh giữa `urls_text` và danh sách URL trong `urls.json`
    và chỉ tải xuống các file mới (tức URL chưa có trong `urls.json`), rồi cập nhật `urls.json`
    và chỉ return lại các file mới được tải.
    """
    # 1. Parse URLs từ `urls_text`
    urls = []
    for line in urls_text.splitlines():
        line = line.strip()
        if line.lower().startswith(("url:", "f.url:")):
            url_part = line.split(":", 1)[1].strip()
            if url_part:
                urls.append(url_part)
    if not urls:
        return {
            "output": f"Không tìm thấy bất kỳ URL nào trong kết quả cho course: {course_name}"}

    # 2. Xác định đường dẫn đến thư mục lưu file cho course
    current_file_path = Path(__file__).resolve()
    downloads_dir = current_file_path.parents[3] / "files"
    safe_course_name = course_name.replace(" ", "_").replace("*", "")
    dir_path = os.path.join(downloads_dir, safe_course_name)

    # 3. Tạo thư mục nếu chưa tồn tại
    try:
        os.makedirs(dir_path, exist_ok=True)
    except Exception as e:
        return {"output": f"Error khi tạo thư mục {dir_path}: {e}"}

    # 4. Xác định file JSON lưu URL đã tải
    json_path = os.path.join(dir_path, "urls.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as jf:
                existing_urls = json.load(jf)
                if not isinstance(existing_urls, list):
                    existing_urls = []
        except Exception:
            # Nếu có lỗi khi đọc, coi như chưa có URL nào
            existing_urls = []
    else:
        existing_urls = []

    # 5. Tìm các URL mới (chưa có trong existing_urls)
    new_urls = [u for u in urls if u not in existing_urls]
    if not new_urls:
        return {"output": "Không có file mới để tải."}

    # 6. Tải các URL mới
    downloaded = []
    for idx, url in enumerate(new_urls, start=1):
        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()

            # Cố gắng lấy filename từ header 'content-disposition' nếu có
            filename = None
            cd = resp.headers.get("content-disposition", "")
            if cd:
                m_star = re.search(
                    r"filename\*\s*=\s*([^;]+)", cd, flags=re.IGNORECASE)

                if m_star:
                    star_value = m_star.group(1).strip()
                    if "''" in star_value:
                        charset, encoded = star_value.split("''", 1)
                        try:
                            filename = urllib.parse.unquote(
                                encoded, encoding=charset or "utf-8", errors="ignore")
                        except BaseException:
                            filename = urllib.parse.unquote(
                                encoded, encoding="utf-8", errors="ignore")
                    else:
                        filename = urllib.parse.unquote(star_value)
                    print(f"m_star: {m_star}")
            if not filename:
                filename = url.split("/")[-1].split("?")[0] or f"file_{idx}"

            # Lưu file vào thư mục course
            file_path = os.path.join(dir_path, filename)
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            downloaded.append(filename)
        except Exception as e:
            downloaded.append(f"ERROR_{idx}: {url} ({e})")

    # 7. Cập nhật lại danh sách URL trong urls.json (ghép existing_urls và
    # new_urls)
    updated_urls = existing_urls + new_urls
    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(updated_urls, jf, ensure_ascii=False, indent=2)
    except Exception as e:
        # Nếu ghi JSON lỗi, nhưng vẫn trả về kết quả tải
        return {
            "output": (
                f"Hoàn thành tải {len(downloaded)} file mới vào '{dir_path}', "
                f"nhưng lỗi khi cập nhật {json_path}: {e}\n"
                + "\n".join(downloaded)
            )
        }

    # 8. Trả về thông báo với danh sách file mới đã tải
    downloaded_list_str = "\n".join(downloaded)
    return {
        "output": (
            f"Hoàn thành tải {len(downloaded)} file mới vào '{dir_path}':\n"
            f"{downloaded_list_str}"
        )
    }


# Initialize Neo4j tools
neo4j_connector = get_neo4j_connector()
cypher_executor_tool, cypher_generator_tool = init_cypher_tools(
    neo4j_connector, get_cypher_llm())