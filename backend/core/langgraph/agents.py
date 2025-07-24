from langgraph.prebuilt import create_react_agent

from backend.core.config import (get_action_build_llm, get_cypher_llm,
                                get_supervisor_llm)
from backend.core.langgraph.neo4j.build_kg_tools.build_knowledge_graph_tools import (
    action_generator_tool, build_knowledge_graph_tool)
from backend.core.langgraph.neo4j.cyper_tools.neo4j_tools import (
    cypher_executor_tool, cypher_generator_tool, download_files_for_course)
from backend.core.prompt.build_knowledge_graph_agent_prompt import (
    build_knowledge_graph_agent_prompt)
from backend.core.prompt.cypher_agent_prompt import cypher_agent_prompt
from backend.core.prompt.supervisor_prompt import supervisor_prompt
from backend.core.langgraph.tools import (
    assign_to_build_knowledge_graph_agent_with_description,
    assign_to_cyper_kg_agent_with_description)


# CYPER KNOWLEDGE GRAPH AGENT
cyper_kg_llm = get_cypher_llm()
cyper_kg_agent = create_react_agent(
    model=cyper_kg_llm,
    tools=[
        cypher_generator_tool,
        cypher_executor_tool,
        download_files_for_course
    ],
    prompt=cypher_agent_prompt,
    name="cyper_kg_agent",
)

# BUILD KNOWLEDGE GRAPH AGENT
database_llm = get_action_build_llm()
build_knowledge_graph_agent = create_react_agent(
    model=database_llm,
    tools=[
        action_generator_tool,
        build_knowledge_graph_tool
    ],
    prompt=build_knowledge_graph_agent_prompt,
    name="build_knowledge_graph_agent",
)

# DEFINE SUPERVISOR AGENT
supervisor_agent_with_description = create_react_agent(
    model=get_supervisor_llm(),
    tools=[
        assign_to_cyper_kg_agent_with_description,
        assign_to_build_knowledge_graph_agent_with_description
    ],
    prompt=supervisor_prompt,
    name="supervisor"
)