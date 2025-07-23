import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from neo4j import GraphDatabase

from backend.core.config import get_action_build_llm
from backend.core.langgraph.neo4j.build_kg_tools.fetch_canvas_data import (
    fetch_assignments, fetch_calendar_events, fetch_communication_channels,
    fetch_courses, fetch_discussion_topics, fetch_files, fetch_quizzes,
    fetch_submissions, fetch_users)
from backend.core.prompt.action_build_generator_prompt import (
    action_build_generator_prompt)

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN")

# Đường dẫn file snapshot
current_dir = os.path.dirname(__file__)
SNAPSHOT_FILE = os.path.join(current_dir, "snapshot.json")
KNOWLEDGE_SNAPSHOT_FILE = os.path.join(current_dir, "knowledge_snapshot.json")

VIETNAM_TZ = timezone(timedelta(hours=7))


def convert_to_vietnam_time(utc_time_str):
    if not utc_time_str:
        return None
    try:
        utc_time = datetime.fromisoformat(utc_time_str.replace('Z', '+00:00'))
        vietnam_time = utc_time.astimezone(VIETNAM_TZ)
        return vietnam_time.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        print(f"Lỗi: Không thể chuyển đổi thời gian {utc_time_str}")
        return utc_time_str  # Giữ nguyên nếu lỗi

# Neo4j Driver


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def close(driver):
    driver.close()

# Hàm lưu snapshot


def save_snapshot(snapshot_data):
    try:
        # Lưu trực tiếp snapshot_data vào file, không cần mảng snapshots nữa
        with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
            json.dump(snapshot_data, f, indent=4)
        print(f"Đã lưu snapshot vào {SNAPSHOT_FILE}")
    except Exception as e:
        print(f"Lỗi khi lưu snapshot: {e}")


def save_diff(diff_data):
    """
    Lưu thông tin những thực thể mới (so với lần snapshot trước)
    vào file diff_<YYYY-MM-DD>.json.
    """
    try:
        # Đặt tên file theo ngày (yyyy-mm-dd)
        diff_filename_base = f"diff_{diff_data.get('date')}.json"

        # Tạo đường dẫn đầy đủ tới file diff trong cùng thư mục với script
        diff_filename = os.path.join(current_dir, diff_filename_base)
        with open(diff_filename, "w", encoding="utf-8") as f:
            json.dump(diff_data, f, indent=4, ensure_ascii=False)
        print(f"Đã lưu diff vào {diff_filename}")
    except Exception as e:
        print(f"Lỗi khi lưu diff: {e}")

# Hàm lấy snapshot gần nhất


def get_latest_snapshot():
    try:
        if os.path.exists(SNAPSHOT_FILE) and os.path.getsize(
                SNAPSHOT_FILE) > 0:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                snapshots = json.load(f)
                if not isinstance(
                        snapshots,
                        dict) or "snapshots" not in snapshots or not snapshots["snapshots"]:
                    print(
                        f"File {SNAPSHOT_FILE} không chứa snapshot hợp lệ, trả về None.")
                    return None
                return max(snapshots["snapshots"], key=lambda x: x["date"])
        print(f"File {SNAPSHOT_FILE} không tồn tại hoặc rỗng, trả về None.")
        return None
    except json.JSONDecodeError:
        print(
            f"File {SNAPSHOT_FILE} rỗng hoặc chứa dữ liệu không hợp lệ, trả về None.")
        return None
    except Exception as e:
        print(f"Lỗi khi đọc snapshot: {e}")
        return None

# Hàm so sánh ID mới và cũ


def get_new_ids(current_ids, entity_type, latest_snapshot):
    if not latest_snapshot or entity_type not in latest_snapshot:
        return current_ids
    previous_ids = set(latest_snapshot.get(entity_type, []))
    return [id for id in current_ids if id not in previous_ids]


def _extract_file_endpoints(description_html):
    """
    Dùng regex để trích tất cả các giá trị của thuộc tính data-api-endpoint.
    """
    # Regex: tìm data-api-endpoint="(…)"
    pattern = r'data-api-endpoint="([^"]+)"'
    return re.findall(pattern, description_html)


def _fetch_file_metadata(api_url):
    """
    Gửi GET request tới Canvas API để lấy metadata của file.
    Trả về dict JSON (hoặc None nếu thất bại).
    """
    headers = {
        "Authorization": f"Bearer {CANVAS_API_TOKEN}",
        "Accept": "application/json"
    }
    resp = requests.get(api_url, headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    else:
        # Bạn có thể log thêm resp.status_code, resp.text để debug
        return None


def _link_files_for_assignment(tx, assignment_id, description_html):
    """
    1. Tách danh sách API endpoints từ description.
    2. Với mỗi endpoint, gọi API để lấy metadata:
       {
         "id": 548418,
         "uuid": "...",
         "display_name": "Use-case.pdf",
         "filename": "Use-case.pdf",
         "url": "https://.../download?...",
         "size": 152629,
         ...
       }
    3. Tạo File node nếu chưa tồn tại
    4. Tạo quan hệ (a)-[:CONTAINS_FILE]->(f).
    """
    endpoints = _extract_file_endpoints(description_html)
    if not endpoints:
        return

    for endpoint in endpoints:
        meta = _fetch_file_metadata(endpoint)
        if not meta or not meta.get("id"):
            continue

        # Đầu tiên, đảm bảo File node tồn tại
        tx.run(
            """
            MERGE (f:File {id: $file_id})
            SET f.filename = $filename,
                f.url = $url,
                f.size = $size
            """,
            file_id=meta["id"],
            filename=meta.get("filename"),
            url=meta.get("url"),
            size=meta.get("size")
        )

        # Sau đó tạo relationship
        tx.run(
            """
            MATCH (a:Assignment {id: $assignment_id})
            MATCH (f:File {id: $file_id})
            MERGE (a)-[:CONTAINS_FILE]->(f)
            """,
            assignment_id=assignment_id,
            file_id=meta["id"]
        )


def create_user(tx, user):
    if not user.get("id"):
        return
    tx.run(
        """
        MERGE (u:User {id: $id})
        SET u.name = $name
        """,
        id=user.get("id"),
        name=user.get("name")
    )


def create_communication_channel(tx, channel):
    tx.run(
        """
        MERGE (ch:CommunicationChannel {id: $id})
        SET ch.type = $type, ch.address = $address
        MERGE (u:User {id: $user_id})
        MERGE (u)-[:HAS_CHANNEL]->(ch)
        """,
        id=channel.get("id"),
        type=channel.get("type"),
        address=channel.get("address"),
        user_id=channel.get("user_id")
    )


def create_course(tx, course, enrollments):
    if not course.get("id"):
        return
    # Chuyển đổi thời gian sang giờ Việt Nam
    start_at = convert_to_vietnam_time(course.get("start_at"))
    end_at = convert_to_vietnam_time(course.get("end_at"))
    tx.run(
        """
        MERGE (c:Course {id: $id})
        SET c.name = $name, c.start_at = $start_at, c.enrollment_term_id = $enrollment_term_id,
            c.end_at = $end_at
        """,
        id=course.get("id"),
        name=course.get("name"),
        enrollment_term_id=course.get("enrollment_term_id"),
        start_at=start_at,
        end_at=end_at
    )
    # Tạo mối quan hệ ENROLLED_IN cho từng enrollment
    for enrollment in enrollments:
        user_id = enrollment.get("user_id")
        if user_id:
            tx.run(
                """
                MERGE (u:User {id: $user_id})
                MERGE (c:Course {id: $course_id})
                MERGE (u)-[:ENROLLED_IN {role: $role, enrollment_state: $enrollment_state}]->(c)
                """,
                user_id=user_id,
                course_id=course.get("id"),
                role=enrollment.get("role"),
                enrollment_state=enrollment.get("enrollment_state")
            )


def create_assignment(tx, assignment, course_id):
    if not assignment.get("id"):
        return
    # Chuyển đổi thời gian sang giờ Việt Nam
    unlock_at = convert_to_vietnam_time(assignment.get("unlock_at"))
    lock_at = convert_to_vietnam_time(assignment.get("lock_at"))
    description = assignment.get("description")
    tx.run(
        """
        MERGE (a:Assignment {id: $id})
        SET a.name = $name, a.unlock_at = $unlock_at, a.lock_at = $lock_at, a.description = $description
        MERGE (c:Course {id: $course_id})
        MERGE (c)-[:CONTAINS]->(a)
        """,
        id=assignment.get("id"),
        lock_at=lock_at,
        name=assignment.get("name"),
        unlock_at=unlock_at,
        description=description,
        course_id=course_id
    )
    if description:
        _link_files_for_assignment(tx, assignment.get("id"), description)


def create_submission(tx, submission, course_id):
    submission_id = submission.get("id")
    assignment_id = submission.get("assignment_id")
    user_id = submission.get("user_id")

    print(
        f"Xử lý submission: {submission}, submission_id: {submission_id}, assignment_id: {assignment_id}, user_id: {user_id}")

    # Generate a deterministic UUID based on submission data
    if submission_id is None:
        # Create a deterministic ID based on assignment_id, user_id, and
        # submitted_at
        unique_data = f"{assignment_id}_{user_id}_{
            submission.get('submitted_at')}"
        submission_id = f"submission_{hash(unique_data)}"

    # Chuyển đổi thời gian sang giờ Việt Nam
    submitted_at = convert_to_vietnam_time(submission.get("submitted_at"))

    # Validate required relationships
    if assignment_id is not None:
        # Check if assignment exists
        result = tx.run(
            "MATCH (a:Assignment {id: $assignment_id}) RETURN a",
            assignment_id=assignment_id)
        if not result.single():
            print(
                f"Warning: Assignment {assignment_id} not found for submission {submission_id}")
            return

    if user_id is not None:
        # Check if user exists
        result = tx.run(
            "MATCH (u:User {id: $user_id}) RETURN u",
            user_id=user_id)
        if not result.single():
            print(
                f"Warning: User {user_id} not found for submission {submission_id}")
            return

    # Create submission with validated relationships
    if assignment_id is not None and user_id is not None:
        tx.run(
            """
            MERGE (s:Submission {id: $submission_id})
            SET s.grade = $grade, s.score = $score, s.submitted_at = $submitted_at,
                s.last_updated = datetime()
            MERGE (a:Assignment {id: $assignment_id})
            MERGE (u:User {id: $user_id})
            MERGE (a)-[:HAS_SUBMISSION]->(s)
            MERGE (u)-[:SUBMITTED]->(s)
            """,
            submission_id=submission_id,
            grade=submission.get("grade"),
            score=submission.get("score"),
            submitted_at=submitted_at,
            assignment_id=assignment_id,
            user_id=user_id
        )
    elif assignment_id is None and user_id is not None:
        tx.run(
            """
            MERGE (s:Submission {id: $submission_id})
            SET s.grade = $grade, s.score = $score, s.submitted_at = $submitted_at
            MERGE (u:User {id: $user_id})
            MERGE (u)-[:SUBMITTED]->(s)
            """,
            submission_id=submission_id,
            grade=submission.get("grade"),
            score=submission.get("score"),
            submitted_at=submitted_at,
            user_id=user_id,
            course_id=course_id
        )
    elif assignment_id is not None and user_id is None:
        tx.run(
            """
            MERGE (s:Submission {id: $submission_id})
            SET s.grade = $grade, s.score = $score, s.submitted_at = $submitted_at
            MERGE (a:Assignment {id: $assignment_id})
            MERGE (a)-[:HAS_SUBMISSION]->(s)
            """,
            submission_id=submission_id,
            grade=submission.get("grade"),
            score=submission.get("score"),
            submitted_at=submitted_at,
            assignment_id=assignment_id,
            course_id=course_id
        )
    elif assignment_id is None and user_id is None:
        tx.run(
            """
            MERGE (s:Submission {id: $submission_id})
            SET s.grade = $grade, s.score = $score, s.submitted_at = $submitted_at
            """,
            submission_id=submission_id,
            grade=submission.get("grade"),
            score=submission.get("score"),
            submitted_at=submitted_at,
            course_id=course_id
        )
    else:
        print(f"Bỏ qua submission vì không đủ thông tin: {submission}")


def create_calendar_event(tx, event, course_id):
    if not event.get("id"):
        return
    start_at = convert_to_vietnam_time(event.get("start_at"))
    end_at = convert_to_vietnam_time(event.get("end_at"))
    tx.run(
        """
        MERGE (e:Calendar {id: $id})
        SET e.title = $title, e.start_at = $start_at, e.end_at = $end_at
        MERGE (c:Course {id: $course_id})
        MERGE (c)-[:HAS_EVENT]->(e)
        """,
        id=event.get("id"),
        title=event.get("title"),
        start_at=start_at,
        end_at=end_at,
        course_id=course_id
    )


def create_discussion_topic(tx, topic, course_id):
    topic_id = topic.get("id")
    assignment_id = topic.get("assignment_id")

    print(
        f"Xử lý discussion topic: {topic}, topic_id: {topic_id}, assignment_id: {assignment_id}, course_id: {course_id}")

    if topic_id is None:
        topic_id = f"unknown_topic_{uuid.uuid4()}"

    if assignment_id is not None:
        tx.run(
            """
            MERGE (d:DiscussionTopic {id: $id})
            SET d.title = $title, d.message = $message, d.discussion_subentry_count = $discussion_subentry_count
            MERGE (c:Course {id: $course_id})
            MERGE (a:Assignment {id: $assignment_id})
            MERGE (c)-[:HAS_TOPIC]->(d)
            """,
            id=topic_id,
            title=topic.get("title"),
            message=topic.get("message"),
            discussion_subentry_count=topic.get("discussion_subentry_count"),
            assignment_id=assignment_id,
            course_id=course_id
        )
    else:
        tx.run(
            """
            MERGE (d:DiscussionTopic {id: $id})
            SET d.title = $title, d.message = $message, d.discussion_subentry_count = $discussion_subentry_count
            MERGE (c:Course {id: $course_id})
            MERGE (c)-[:HAS_TOPIC]->(d)
            """,
            id=topic_id,
            title=topic.get("title"),
            message=topic.get("message"),
            discussion_subentry_count=topic.get("discussion_subentry_count"),
            course_id=course_id
        )


def create_file(tx, file, course_id):
    if not file.get("id"):
        return
    tx.run(
        """
        MERGE (f:File {id: $id})
        SET f.filename = $filename, f.url = $url, f.size = $size
        MERGE (c:Course {id: $course_id})
        MERGE (c)-[:HAS_FILE]->(f)
        """,
        id=file.get("id"),
        filename=file.get("filename"),
        size=file.get("size"),
        url=file.get("url"),
        course_id=course_id
    )


def create_quiz(tx, quiz, course_id):
    quiz_id = quiz.get("id") or f"unknown_quiz_{uuid.uuid4()}"
    assignment_id = quiz.get("assignment_id")

    # Gán giá trị mặc định là null nếu thuộc tính không tồn tại
    title = quiz.get("title")
    quiz_type = quiz.get("quiz_type")
    time_limit = quiz.get("time_limit")
    shuffle_answers = quiz.get("shuffle_answers")
    show_correct_answers = quiz.get("show_correct_answers")
    allowed_attempts = quiz.get("allowed_attempts")
    question_count = quiz.get("question_count")
    cant_go_back = quiz.get("cant_go_back")
    # Chuyển đổi thời gian sang giờ Việt Nam
    lock_at = convert_to_vietnam_time(quiz.get("lock_at"))
    unlock_at = convert_to_vietnam_time(quiz.get("unlock_at"))

    if assignment_id is not None:
        tx.run(
            """
            MERGE (q:Quiz {id: $id})
            SET q.title = $title, q.quiz_type = $quiz_type, q.time_limit = $time_limit,
                q.shuffle_answers = $shuffle_answers, q.show_correct_answers = $show_correct_answers,
                q.allowed_attempts = $allowed_attempts, q.question_count = $question_count,
                q.cant_go_back = $cant_go_back, q.lock_at = $lock_at, q.unlock_at = $unlock_at
            MERGE (a:Assignment {id: $assignment_id})
            MERGE (c:Course {id: $course_id})
            MERGE (c)-[:HAS_QUIZ]->(q)
            MERGE (a)-[:CONTAINS_QUIZ]->(q)
            """,
            id=quiz_id,
            title=title,
            quiz_type=quiz_type,
            time_limit=time_limit,
            shuffle_answers=shuffle_answers,
            show_correct_answers=show_correct_answers,
            allowed_attempts=allowed_attempts,
            question_count=question_count,
            cant_go_back=cant_go_back,
            lock_at=lock_at,
            unlock_at=unlock_at,
            assignment_id=assignment_id,
            course_id=course_id
        )
    else:
        tx.run(
            """
            MERGE (q:Quiz {id: $id})
            SET q.title = $title, q.quiz_type = $quiz_type, q.time_limit = $time_limit,
                q.shuffle_answers = $shuffle_answers, q.show_correct_answers = $show_correct_answers,
                q.allowed_attempts = $allowed_attempts, q.question_count = $question_count,
                q.cant_go_back = $cant_go_back, q.lock_at = $lock_at, q.unlock_at = $unlock_at
            MERGE (c:Course {id: $course_id})
            MERGE (c)-[:HAS_QUIZ]->(q)
            """,
            id=quiz_id,
            title=title,
            quiz_type=quiz_type,
            time_limit=time_limit,
            shuffle_answers=shuffle_answers,
            show_correct_answers=show_correct_answers,
            allowed_attempts=allowed_attempts,
            question_count=question_count,
            cant_go_back=cant_go_back,
            lock_at=lock_at,
            unlock_at=unlock_at,
            course_id=course_id
        )


def build_graph(driver: GraphDatabase.driver):
    # Đọc snapshot hiện tại nếu có
    current_snapshot = None
    if os.path.exists(SNAPSHOT_FILE) and os.path.getsize(SNAPSHOT_FILE) > 0:
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                current_snapshot = json.load(f)
        except json.JSONDecodeError:
            print(f"File {SNAPSHOT_FILE} rỗng hoặc chứa dữ liệu không hợp lệ.")
            current_snapshot = None

    # Chuẩn bị cấu trúc snapshot_data
    snapshot_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "users": [],
        "courses": [],
        "assignments": [],
        "submissions": [],
        "calendar_events": [],
        "discussion_topics": [],
        "files": [],
        "quizzes": [],
        "communication_channels": [],
        "enrollments": []
    }
    # Chuẩn bị diff_data chỉ chứa các phần tử mới
    diff_data = {
        "date": snapshot_data["date"],
        "new_users": [],
        "new_courses": [],
        "new_assignments": [],
        "new_submissions": [],
        "new_calendar_events": [],
        "new_discussion_topics": [],
        "new_files": [],
        "new_quizzes": [],
        "new_communication_channels": [],
        "new_enrollments": []
    }

    try:
        with driver.session() as session:
            with session.begin_transaction() as tx:
                try:
                    # ==== XỬ LÝ USER & COMMUNICATION CHANNELS ====
                    user = fetch_users() or {}
                    user_id = user.get("id")
                    if user_id:
                        snapshot_data["users"].append(user_id)
                        # Nếu user_id chưa có trong current_snapshot thì thêm
                        # mới
                        if not current_snapshot or user_id not in current_snapshot.get("users", [
                        ]):
                            create_user(tx, user)
                            diff_data["new_users"].append(user_id)

                        # Lấy thông tin communication channels của user
                        channels = fetch_communication_channels() or []
                        for channel in channels:
                            channel_id = channel.get("id")
                            if not channel_id:
                                continue
                            snapshot_data["communication_channels"].append(
                                channel_id)
                            if not current_snapshot or channel_id not in current_snapshot.get(
                                    "communication_channels", []):
                                create_communication_channel(tx, channel)
                                diff_data["new_communication_channels"].append(
                                    channel_id)

                    # ==== XỬ LÝ CÁC KHÓA HỌC, ASSIGNMENTS, SUBMISSIONS, ... ====
                    courses = fetch_courses() or []
                    for course in courses:
                        course_id = course.get("id")
                        if not course_id:
                            continue
                        snapshot_data["courses"].append(course_id)
                        # Nếu khóa học mới so với current_snapshot
                        if not current_snapshot or course_id not in current_snapshot.get("courses", [
                        ]):
                            # Tạo mới toàn bộ course (bao gồm enrollments mới
                            # của user)
                            enrollments = [
                                e for e in course.get(
                                    "enrollments",
                                    []) if e.get("user_id") == user_id]
                            create_course(tx, course, enrollments)
                            diff_data["new_courses"].append(course_id)

                            # Đưa tất cả enrollments của user trong khóa học
                            # này vào diff
                            for e in enrollments:
                                enroll_key = f"{e.get('user_id')}_{course_id}"
                                diff_data["new_enrollments"].append(enroll_key)
                        else:
                            # Nếu khóa học đã có, thì chỉ quan tâm enrollments
                            # mới
                            enrollments = [
                                e for e in course.get(
                                    "enrollments",
                                    []) if e.get("user_id") == user_id]
                            enrollment_ids = [
                                f"{e.get('user_id')}_{course_id}" for e in enrollments if e.get("user_id")]
                            new_enrollment_ids = [
                                id for id in enrollment_ids if not current_snapshot or id not in current_snapshot.get(
                                    "enrollments", [])]
                            new_enrollments = [
                                e for e in enrollments if f"{
                                    e.get('user_id')}_{course_id}" in new_enrollment_ids]
                            # Nếu có enrollment mới, vẫn gọi create_course để
                            # chỉ tạo quan hệ ENROLLED_IN
                            if new_enrollments:
                                create_course(tx, course, new_enrollments)
                                diff_data["new_enrollments"].extend(
                                    new_enrollment_ids)

                        # LUU snapshot enrollments (dù đã có hay chưa)
                        for e in course.get("enrollments", []) or []:
                            if e.get("user_id"):
                                enroll_key = f"{e.get('user_id')}_{course_id}"
                                snapshot_data["enrollments"].append(enroll_key)
                        # ===== FILES =====
                        files = fetch_files(course_id) or []
                        for file in files:
                            file_id = file.get("id")
                            if not file_id:
                                continue
                            snapshot_data["files"].append(file_id)
                            if not current_snapshot or file_id not in current_snapshot.get("files", [
                            ]):
                                create_file(tx, file, course_id)
                                diff_data["new_files"].append(file_id)

                        # ===== ASSIGNMENTS =====
                        assignments = fetch_assignments(course_id) or []
                        for assignment in assignments:
                            assignment_id = assignment.get("id")
                            if not assignment_id:
                                continue
                            snapshot_data["assignments"].append(assignment_id)
                            if not current_snapshot or assignment_id not in current_snapshot.get(
                                    "assignments", []):
                                create_assignment(tx, assignment, course_id)
                                diff_data["new_assignments"].append(
                                    assignment_id)

                        # ===== SUBMISSIONS =====
                        submissions = fetch_submissions(course_id) or []
                        for submission in submissions:
                            submission_id = submission.get(
                                "id") or f"unknown_submission_{uuid.uuid4()}"
                            snapshot_data["submissions"].append(submission_id)
                            if not current_snapshot or submission_id not in current_snapshot.get(
                                    "submissions", []):
                                create_submission(tx, submission, course_id)
                                diff_data["new_submissions"].append(
                                    submission_id)

                        # ===== CALENDAR EVENTS =====
                        calendar_events = fetch_calendar_events(
                            course_id) or []
                        for event in calendar_events:
                            event_id = event.get("id")
                            if not event_id:
                                continue
                            snapshot_data["calendar_events"].append(event_id)
                            if not current_snapshot or event_id not in current_snapshot.get(
                                    "calendar_events", []):
                                create_calendar_event(tx, event, course_id)
                                diff_data["new_calendar_events"].append(
                                    event_id)

                        # ===== DISCUSSION TOPICS =====
                        discussion_topics = fetch_discussion_topics(
                            course_id) or []
                        for topic in discussion_topics:
                            topic_id = topic.get(
                                "id") or f"unknown_topic_{uuid.uuid4()}"
                            snapshot_data["discussion_topics"].append(topic_id)
                            if not current_snapshot or topic_id not in current_snapshot.get(
                                    "discussion_topics", []):
                                create_discussion_topic(tx, topic, course_id)
                                diff_data["new_discussion_topics"].append(
                                    topic_id)

                        # ===== QUIZZES =====
                        try:
                            quizzes = fetch_quizzes(course_id) or []
                        except Exception:
                            quizzes = []
                        for quiz in quizzes:
                            quiz_id = quiz.get(
                                "id") or f"unknown_quiz_{uuid.uuid4()}"
                            snapshot_data["quizzes"].append(quiz_id)
                            if not current_snapshot or quiz_id not in current_snapshot.get("quizzes", [
                            ]):
                                create_quiz(tx, quiz, course_id)
                                diff_data["new_quizzes"].append(quiz_id)

                    # Nếu không có lỗi, commit transaction
                    print("COMMIT")
                    tx.commit()
                except Exception as e:
                    print(f"Error during graph build: {str(e)}")
                    tx.rollback()
                    raise

    except Exception as e:
        print(f"Failed to build knowledge graph: {str(e)}")
        raise
    finally:
        # Luôn lưu snapshot mới (dù diff có rỗng hay không)
        save_snapshot(snapshot_data)
        # Lưu diff (nếu có phần tử mới, hoặc có thể lưu cả khi rỗng để tiện tra
        # cứu)
        save_diff(diff_data)

    # Trả về diff_data để có thể sử dụng khi gọi tool
    return diff_data


def delete_graph(driver: GraphDatabase.driver):
    snapshot_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "users": [],
        "courses": [],
        "assignments": [],
        "submissions": [],
        "calendar_events": [],
        "discussion_topics": [],
        "files": [],
        "quizzes": [],
        "communication_channels": [],
        "enrollments": []
    }
    # Chuẩn bị diff_data chỉ chứa các phần tử mới
    diff_data = {
        "date": snapshot_data["date"],
        "new_users": [],
        "new_courses": [],
        "new_assignments": [],
        "new_submissions": [],
        "new_calendar_events": [],
        "new_discussion_topics": [],
        "new_files": [],
        "new_quizzes": [],
        "new_communication_channels": [],
        "new_enrollments": []
    }

    try:
        with driver.session() as session:
            with session.begin_transaction() as tx:
                try:
                    tx.run(
                        """
                    MATCH (n) DETACH DELETE n
                    """
                    )
                    tx.commit()
                except Exception as e:
                    print(f"Error during graph build: {str(e)}")
                    tx.rollback()
                    raise
    except Exception as e:
        print(f"Failed to delete knowledge graph: {str(e)}")
        raise
    finally:
        save_snapshot(snapshot_data)
        save_diff(diff_data)


def init_build_knowledge_graph_tools(
        driver: GraphDatabase.driver,
        llm_for_action):
    prompt_template = PromptTemplate(
        template=action_build_generator_prompt,
        input_variables=["nl_question"]
    )

    def action_generator_tool(nl_question: str) -> dict:
        """
        Tool để chuyển câu hỏi ngôn ngữ tự nhiên thành action (string).
        """
        try:
            if isinstance(nl_question, dict):
                if nl_question.get("status"):
                    return {"output": "NONE"}
                nl_question = str(nl_question)

            # Tạo prompt string từ template
            prompt_str = prompt_template.format(nl_question=nl_question)

            # Gọi LLM với chuỗi đã được format sẵn
            response = llm_for_action.invoke(prompt_str)

            # Xử lý kết quả
            if hasattr(response, "content"):
                action = response.content
            else:
                action = str(response)

            action_cleaned = action.strip().strip('"').strip("'").lower()
            return {"output": action_cleaned or "NONE"}

        except Exception as e:
            print(f"[action_generator_tool] Error: {str(e)}")
            return {"output": "NONE"}

    def build_knowledge_graph_tool(action: str):
        """Build or update the knowledge graph with Canvas data.

        Args:
            action (str): Hiện chỉ hỗ trợ "build" hoặc "delete".

        Trả về:
            dict: Dictionary chứa status và data (nếu có)
                - status: "success" hoặc "error"
                - message: Thông báo kết quả
                - data: diff_data (nếu là action build) hoặc None
        """
        if action == "build":
            try:
                diff_data = build_graph(driver)
                # Tính tổng số mới thêm của từng loại
                summary_lines = []
                summary_lines.append(
                    f"Users mới: {len(diff_data.get('new_users', []))}")
                summary_lines.append(
                    f"CommunicationChannels mới: {len(diff_data.get('new_communication_channels', []))}")
                summary_lines.append(
                    f"Courses mới: {len(diff_data.get('new_courses', []))}")
                summary_lines.append(
                    f"Enrollments mới: {len(diff_data.get('new_enrollments', []))}")
                summary_lines.append(
                    f"Assignments mới: {len(diff_data.get('new_assignments', []))}")
                summary_lines.append(
                    f"Submissions mới: {len(diff_data.get('new_submissions', []))}")
                summary_lines.append(
                    f"CalendarEvents mới: {len(diff_data.get('new_calendar_events', []))}")
                summary_lines.append(
                    f"DiscussionTopics mới: {len(diff_data.get('new_discussion_topics', []))}")
                summary_lines.append(
                    f"Files mới: {len(diff_data.get('new_files', []))}")
                summary_lines.append(
                    f"Quizzes mới: {len(diff_data.get('new_quizzes', []))}")

                summary_text = "\n".join(summary_lines)
                return {
                    "status": "success",
                    "message": f"Build knowledge graph success.\n====== SUMMARY ======\n{summary_text}",
                    "data": diff_data}
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Build knowledge graph failed: {e}",
                    "data": None
                }
        elif action == "delete":
            try:
                delete_graph(driver)
                return {
                    "status": "success",
                    "message": "Delete knowledge graph success.",
                    "data": None
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Delete knowledge graph failed: {e}",
                    "data": None
                }
        else:
            return {
                "status": "error",
                "message": f"Invalid action: {action}. Supported actions are 'build' and 'delete'.",
                "data": None}
    return action_generator_tool, build_knowledge_graph_tool


driver = get_driver()
action_generator_tool, build_knowledge_graph_tool = init_build_knowledge_graph_tools(
    driver, get_action_build_llm())
# build_graph(driver))