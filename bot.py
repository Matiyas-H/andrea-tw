import aiohttp
import os
import sys
from pipecat.frames.frames import EndFrame, LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import (
    LLMAssistantResponseAggregator,
    LLMUserResponseAggregator
)
from pipecat.services.openai import OpenAILLMService
from pipecat.services.deepgram import DeepgramSTTService, DeepgramTTSService
from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.serializers.twilio import TwilioFrameSerializer

from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

async def run_bot(websocket_client, stream_sid, is_outbound=False):
    logger.info(f"Starting run_bot with stream_sid: {stream_sid}, is_outbound: {is_outbound}")
    async with aiohttp.ClientSession() as session:
        transport = FastAPIWebsocketTransport(
            websocket=websocket_client,
            params=FastAPIWebsocketParams(
                audio_out_enabled=True,
                add_wav_header=False,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
                vad_audio_passthrough=True,
                serializer=TwilioFrameSerializer(stream_sid)
            )
        )

        llm = OpenAILLMService(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-3.5-turbo")

        stt = DeepgramSTTService(api_key=os.getenv('DEEPGRAM_API_KEY'))

        tts = DeepgramTTSService(
            aiohttp_session=session,
            api_key=os.getenv("DEEPGRAM_API_KEY"))

        messages = [
            {
                "role": "system",
                "content": "You are an AI assistant making an outbound call." if is_outbound else "You are an AI assistant handling an inbound call.",
            },
        ]

        tma_in = LLMUserResponseAggregator(messages)
        tma_out = LLMAssistantResponseAggregator(messages)

        pipeline = Pipeline([
            transport.input(),   # Websocket input from client
            stt,                 # Speech-To-Text
            tma_in,              # User responses
            llm,                 # LLM
            tts,                 # Text-To-Speech
            transport.output(),  # Websocket output to client
            tma_out              # LLM responses
        ])

        task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            # Kick off the conversation.
            intro_message = "Hello, this is an AI assistant calling. How may I assist you today?" if is_outbound else "Hello, thank you for calling. How may I assist you today?"
            messages.append({"role": "system", "content": intro_message})
            await task.queue_frames([LLMMessagesFrame(messages)])

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            await task.queue_frames([EndFrame()])

        runner = PipelineRunner(handle_sigint=False)

        try:
            # We don't need to explicitly call start() on stt
            await runner.run(task)
        except Exception as e:
            logger.error(f"Error in run_bot: {str(e)}")
        finally:
            # Create an EndFrame to pass to the stop method
            end_frame = EndFrame()
            await stt.stop(end_frame)  # Pass the EndFrame to the stop method
            if not websocket_client.client_state == websocket_client.client_state.DISCONNECTED:
                await websocket_client.close()