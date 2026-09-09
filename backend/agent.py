from typing import Annotated
from typing_extensions import TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt import tools_condition

from duckduckgo_search import DDGS

class State(TypedDict):
    messages: Annotated[list, add_messages]
    
@tool
def web_research_tool(query: str) -> str:
    """
    Use this tool to do web search for factual data regarding any concept or company
    """
    
    print(f"Starting web research for query: {query}")
    
    results = DDGS().text(
        query,
        max_results = 10
    )
    
    if not results:
        return "No results found"
    
    output = []
    
    for item in results:
        output.append(f"Title: {item['title']}\nURL: {item['href']}\nDescription: {item['body']}\n")
        
    return "\n".join(output)


llm = ChatOpenAI(
    model="openrouter/free",
    temperature=0,
    base_url="https://openrouter.ai/api/v1",
)

tools = [web_research_tool]
llm_with_tools = llm.bind_tools(tools)


#agent node
def agent(state: State):
    response = llm_with_tools.invoke(
        state["messages"]
    )
    
    return {
        "messages": [response]
    }
        
   
#langgraph graph building
graph = StateGraph(State)
graph.add_node("agent", agent)
graph.add_node("tools", ToolNode(tools))

graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent",
    tools_condition
)
 
graph.add_edge("tools", "agent")
app = graph.compile()

