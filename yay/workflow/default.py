from .workflow import (
    Workflow,
    Step,
    Finish,
)

from ..events import *


class DefaultAgentStep(Step):

    async def run(self, agent, ctx):

        while True:

            await agent.bus.emit(ModelProcessingEvent())

            response = await agent.provider.process_stream(
                agent.context,
                on_chunk=lambda c: agent._stream_chunk(c),
            )

            agent.context.append(response)

            await agent.bus.emit(
                ProviderResponseEvent(
                    message=response
                )
            )

            tool_calls = agent._extract_tool_calls(response)

            if not tool_calls:

                text = (
                    getattr(
                        getattr(response, "content", None),
                        "text",
                        "",
                    )
                    or ""
                ).strip()

                if not text:
                    raise RuntimeError(
                        "Empty model response"
                    )

                await agent.bus.emit(
                    TaskFinishedEvent(
                        result=text
                    )
                )

                return Finish(text)

            for call in tool_calls:

                await agent._execute_tool(call)


def create_default_workflow():

    workflow = Workflow()

    workflow.node(
        "agent",
        DefaultAgentStep(),
    )

    return workflow