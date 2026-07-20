"""Optional framework integrations for AgentScope.

Each integration lives in its own module and imports its third-party framework
**lazily**, so importing :mod:`agentscope` never pulls in LangChain, LlamaIndex,
etc. Install the matching extra to use one, e.g.::

    pip install "agentscope-lite[langchain]"

Then import the handler explicitly::

    from agentscope.integrations.langchain import AgentScopeCallbackHandler
"""
