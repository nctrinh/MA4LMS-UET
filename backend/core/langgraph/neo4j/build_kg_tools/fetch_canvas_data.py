import os
import time

import requests
from dotenv import load_dotenv

# Tải biến môi trường
load_dotenv()

# Cấu hình Canvas API
CANVAS_API_URL = os.getenv("CANVAS_API_URL")
CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN")
headers = {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}


def fetch_all_pages(url, params=None):
    """
    Lấy tất cả dữ liệu từ endpoint, sử dụng page=1, page=2,...
    Dừng khi không còn trang tiếp theo (dựa trên header Link) hoặc dữ liệu rỗng.
    """
    if params is None:
        params = {}
    params['per_page'] = 50  # Giảm xuống 50 để tăng tốc độ
    all_data = []
    page = 1
    max_pages = 10  # Giới hạn số trang tối đa để tránh lặp vô hạn
    timeout = 30  # Timeout in seconds

    while page <= max_pages:
        try:
            start_time = time.time()
            params['page'] = page
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout)
            response.raise_for_status()
            data = response.json()

            # Nếu dữ liệu rỗng, thoát vòng lặp
            if not data:
                break

            # Thêm dữ liệu vào all_data
            if isinstance(data, list):
                all_data.extend(data)
            else:
                all_data.append(data)

            # Kiểm tra header Link để xem có trang tiếp theo không
            link_header = response.headers.get('Link', '')
            if 'rel="next"' not in link_header:
                break  # Không còn trang tiếp theo

            page += 1
            # Calculate remaining time to respect rate limits
            elapsed = time.time() - start_time
            if elapsed < 0.5:  # Canvas API typically has a rate limit of 2 requests per second
                time.sleep(0.5 - elapsed)
        except requests.RequestException as e:
            print(f"Error fetching page {page} from {url}: {str(e)}")
            if isinstance(e, requests.Timeout):
                print("Request timed out. Consider increasing the timeout value.")
            elif isinstance(e, requests.HTTPError):
                if e.response.status_code == 429:  # Rate limit exceeded
                    print("Rate limit exceeded. Waiting before retrying...")
                    time.sleep(5)  # Wait 5 seconds before retrying
                    continue
                elif e.response.status_code >= 500:  # Server error
                    print("Server error. Waiting before retrying...")
                    time.sleep(2)
                    continue
            raise  # Re-raise the exception to be handled by the caller

    return all_data


def fetch_users():
    """
    Lấy thông tin người dùng hiện tại (self), không cần phân trang
    """
    try:
        response = requests.get(
            f"{CANVAS_API_URL}/users/self",
            headers=headers,
            timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching user data: {str(e)}")
        raise  # Re-raise to be handled by caller


def fetch_courses():
    """
    Lấy tất cả các khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_assignments(course_id):
    """
    Lấy tất cả bài tập của một khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses/{course_id}/assignments"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_submissions(course_id):
    """
    Lấy tất cả bài nộp của một khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses/{course_id}/students/submissions"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_calendar_events(course_id):
    """
    Lấy tất cả sự kiện lịch
    """
    try:
        url = f"{CANVAS_API_URL}/calendar_events"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_discussion_topics(course_id):
    """
    Lấy tất cả chủ đề thảo luận của một khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses/{course_id}/discussion_topics"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_files(course_id):
    """
    Lấy tất cả file của một khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses/{course_id}/files"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_quizzes(course_id):
    """
    Lấy tất cả bài kiểm tra của một khóa học
    """
    try:
        url = f"{CANVAS_API_URL}/courses/{course_id}/quizzes"
        return fetch_all_pages(url)
    except requests.RequestException as e:
        return []


def fetch_communication_channels():
    """
    Lấy tất cả kênh liên lạc của người dùng, không cần phân trang
    """
    try:
        response = requests.get(
            f"{CANVAS_API_URL}/users/self/communication_channels",
            headers=headers,
            timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return []