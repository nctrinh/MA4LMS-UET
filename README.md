# MA4LMS-UET

**MA4LMS-UET** is a multi-agent system designed to assist students at the University of Engineering and Technology (UET) in their learning process. It leverages LLMs and structured workflows to provide intelligent, modular support for tasks such as retrieving course materials, managing knowledge graphs, and delegating responsibilities among agents.

---

## 🔧 Installation & Setup

Follow the steps below to install and run the project locally.

1.  **Clone the repository**
    ```bash
    git clone https://github.com/nctrinh/MA4LMS-UET.git
    cd MA4LMS-UET
    ```
2.  **Create a virtual environment**
    ```bash
    # Using venv
    python -m venv .venv
    source .venv/bin/activate       # On Linux/Mac
    .venv\Scripts\activate          # On Windows
    ```
3.  **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Set up environment variables**
    Copy the `.env.example` file and fill in your credentials and configuration:
    ```bash
    cp .env.example .env  # or manually copy on Windows
    ```
5.  **Run the project**
    Start the project with Langgraph Studio using:
    ```bash
    langgraph dev
    ```

---

## 🤖 Multi-Agent Architecture

The system is built with a modular multi-agent design, including:

* **supervisor_agent**
    The central coordinator. It receives user input, routes tasks to the appropriate agent, and returns the final result.

* **kg_agent**
    Handles information retrieval and course-related queries, such as listing courses, downloading files, or checking assignments.

* **build_knowledge_graph_agent**
    Responsible for constructing and updating the knowledge graph database that represents course and learning content structure.
