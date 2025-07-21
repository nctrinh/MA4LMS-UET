from typing import Annotated

from langchain_core.tools import tool
from langgraph.graph import MessagesState
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, Send


# HANDOFFS
def create_task_description_handoff_tool(
    *, agent_name: str, description: str | None = None
):
    name = f"transfer_to_{agent_name}"
    description = description or f"Ask {agent_name} for help."

    @tool(name, description=description)
    def handoff_tool(
        # this is populated by the supervisor LLM
        task_description: Annotated[
            str,
            "Description of what the next agent should do, including all of the relevant context.",
        ],
        # these parameters are ignored by the LLM
        state: Annotated[MessagesState, InjectedState],
    ) -> Command:
        task_description_message = {
            "role": "user", "content": task_description}
        agent_input = {**state, "messages": [task_description_message]}
        return Command(
            # highlight-next-line
            goto=[Send(agent_name, agent_input)],
            graph=Command.PARENT,
        )
    return handoff_tool


assign_to_cyper_kg_agent_with_description = create_task_description_handoff_tool(
    agent_name="cyper_kg_agent", description="Assign task to a cyper kg agent", )
assign_to_build_knowledge_graph_agent_with_description = create_task_description_handoff_tool(
    agent_name="build_knowledge_graph_agent",
    description="Assign task to a build knowledge graph agent.",
)