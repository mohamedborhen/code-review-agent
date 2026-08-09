print("test1")

from dotenv import load_dotenv
load_dotenv("backend/src/code_review_agent/.env")
from langchain.chat_models import init_chat_model
from langchain_core.tools import StructuredTool

m = init_chat_model("nvidia:nvidia/nemotron-3-ultra-550b-a55b",max_tokens=1024, temperature=0.1, timeout=300)
print(m.__class__.__name__)   # expect: ChatNVIDIA
print(m.model)               # expect: nvidia/nemotron-3-super-120b-a12b

print("test2")

# a tool whose schema contains Optional params — the same anyOf-[X,null] shape
def probe_fn(x: int | None = None):
    """probe tool."""
    return x

tool = StructuredTool.from_function(probe_fn)
bound = m.bind_tools([tool])
resp = bound.invoke("call the probe tool")
print(resp)   # if this prints a tool-call response → tool calling works on NIM