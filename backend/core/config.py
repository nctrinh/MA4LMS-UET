from langchain_openai import ChatOpenAI



# Supervisor LLM
def get_supervisor_llm(temperature: float = 0.7, top_p: float = 0.8):
    return ChatOpenAI(
        model="gpt-4.1-nano",
        temperature=temperature,
        top_p=top_p,
    )


# Cypher LLM
def get_cypher_llm(temperature: float = 0.7, top_p: float = 0.8):
    return ChatOpenAI(
        model="gpt-4.1-nano",
        temperature=temperature,
        top_p=top_p,
    )


def get_action_build_llm(temperature: float = 0.7, top_p: float = 0.8):
    return ChatOpenAI(
        model="gpt-4.1-nano",
        temperature=temperature,
        top_p=top_p,
    )