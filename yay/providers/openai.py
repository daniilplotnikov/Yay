import json
from openai import OpenAI
from ..llm import Model, Message, Content

class OpenAiModel(Model):
    def __init__(self, api_key: str, model: str, tools: list = None):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.tools = tools or []

    def _messages(self, context):
        return [
            {
                "role": m.role,
                "content": m.content.text
            }
            for m in context.messages
        ]

    def _tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.arguments
                }
            }
            for t in self.tools
        ]

    def process(self, context):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages(context),
            tools=self._tools() if self.tools else None,
            tool_choice="auto"
        )

        msg = resp.choices[0].message

        if getattr(msg, "tool_calls", None):

            tc = msg.tool_calls[0]
            name = tc.function.name

            try:
                args = json.loads(tc.function.arguments)
            except:
                args = {}

            return Message(
                role="agent",
                content=Content(text=""),
                tool={
                    "name": name,
                    "arguments": args
                }
            )

        return Message(
            role="agent",
            content=Content(text=msg.content or ""),
            tool=None
        )