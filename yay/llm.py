from datetime import datetime, timezone
from .tool import Tool

class Content():
    def __init__(self, text):
        self.text = text

class Message:
    def __init__(
        self,
        content: Content,
        role: str,
        tool=None
    ):
        self.content = content
        self.role = role
        self.tool = tool
        self.time = datetime.now(timezone.utc)
        
class Context():
    def __init__(self):
        self.messages = []

    def append(self, message: Message):
        self.messages.append(message)

class Model():
    def __init__(self):
        pass

    def process(self, context):

        output = Message(content=Content(text=''), role="agent")

        return output